"""Dedicated NEWS folder and 2-tab OBS playout regression for version 0.4.9."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from library import MediaItem, load_settings, save_settings
from media_search_index import IndexedMediaLibrary
from news_library import belongs_to_news, combined_roots, in_tab, scoped_count


class NewsLibraryPartitionTests(unittest.TestCase):
    def test_news_folder_nested_in_main_is_not_duplicated(self):
        items = [
            MediaItem("D:/Factage/NOVYNY/clip.mp4", "clip.mp4", "video", 123),
            MediaItem("D:/Factage/NOVYNY/photo.jpg", "photo.jpg", "photo", 456),
            MediaItem("D:/Factage/main.mp4", "main.mp4", "video", 789),
            MediaItem("D:/Factage/NOVYNY/audio.mp3", "audio.mp3", "video", 321),
        ]
        root = "D:/Factage/NOVYNY"
        self.assertEqual(scoped_count(items, root, "news"), 2)
        self.assertEqual(scoped_count(items, root, "main"), 1)
        self.assertFalse(in_tab(items[3], root, "news"))
        self.assertFalse(in_tab(items[3], root, "main"))
        # Audio-only files in the NEWS subtree are never shown accidentally.

    def test_prefix_collision_does_not_swallow_unrelated_folders(self):
        root = "D:/Factage/News"
        self.assertTrue(belongs_to_news("D:/Factage/News/sub/post.png", root))
        self.assertFalse(belongs_to_news("D:/Factage/Newsletter/post.png", root))
        self.assertFalse(belongs_to_news("D:/Factage/New/post.png", root))
        self.assertFalse(belongs_to_news("D:/Other/post.png", root))
        self.assertFalse(belongs_to_news("D:/Factage/News/post.png", ""))
        with self.assertRaises(ValueError):
            in_tab(MediaItem("D:/a.mp4", "a.mp4", "video", 1), root, "unknown")

    def test_scan_roots_deduplicate_and_preserve_existing_main_roots(self):
        a = ["D:/factage", "E:/archive"]
        self.assertEqual(combined_roots(a, "D:/factage"),
                         ["D:/factage", "E:/archive"])
        self.assertEqual(combined_roots(a, "C:/news"),
                         ["D:/factage", "E:/archive", "C:/news"])
        self.assertEqual(a, ["D:/factage", "E:/archive"])

    def test_settings_backwards_compatible_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "settings.json"
            save_settings({"roots": ["D:/factage"], "favorites": []}, file)
            self.assertEqual(load_settings(file)["news_folder"], "")
            self.assertFalse(load_settings(file)["news_tab_active"])
            save_settings({"roots": ["D:/factage"], "favorites": [],
                           "news_folder": "E:/novyny",
                           "news_tab_active": True}, file)
            settings = load_settings(file)
            self.assertEqual(settings["roots"], ["D:/factage"])
            self.assertEqual(settings["news_folder"], "E:/novyny")
            self.assertTrue(settings["news_tab_active"])

    def test_scan_media_finds_images_and_videos_in_nested_news_folder(self):
        from library import scan_media
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            news = folder / "news"
            sub = news / "today"
            sub.mkdir(parents=True)
            for file in ["post.mp4", "photo.jpeg", "record.wav", "ignored.txt"]:
                (sub / file).write_bytes(b"test")
            items = scan_media([root, str(news)])
            self.assertEqual({m.name for m in items}, {"post.mp4", "photo.jpeg", "record.wav"})
            self.assertEqual(scoped_count(items, str(news), "news"), 2)


class NewsTabInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build(self):
        from app import MainWindow
        default = load_settings(Path(tempfile.gettempdir()) / "__rg_news_tab_missing_settings__.json")
        default["roots"] = []
        default["news_folder"] = ""
        default["news_tab_active"] = False
        load = patch("app.load_settings", return_value=default)
        save = patch("app.save_settings")
        # The OS is not allowed to register hotkeys during UI regression tests.
        arguments = patch("app.sys.argv", ["rg-test", "--selftest"])
        load.start()
        save.start()
        arguments.start()
        try:
            window = MainWindow()
        finally:
            arguments.stop()
            load.stop()
            save.stop()
        self.addCleanup(window.close)
        return window

    def test_2_tabs_and_no_broadcast_interruption_on_switch(self):
        window = self._build()
        self.assertEqual(window.library_tabs.count(), 2)
        self.assertEqual(window.library_tabs.tabText(0), "ФАКТАЖ")
        self.assertIn("НОВИНИ", window.library_tabs.tabText(1))
        self.assertFalse(window.news_folder_bar.isVisible())
        with patch.object(window, "_save") as saver, \
             patch.object(window.preview, "_cancel_staged") as cancel, \
             patch.object(window, "stop_playback") as stop:
            window.library_tabs.setCurrentIndex(1)
            self.assertEqual(window._current_library_tab, 1)
            self.assertFalse(window.collection_filter.isVisible())
            self.assertTrue(window.news_folder_bar.isVisible() or window.news_folder_bar.isHidden() is False)
            stop.assert_not_called()
            cancel.assert_called_once()
            saver.assert_called_once()

    def test_search_and_media_counts_are_independent(self):
        window = self._build()
        window.news_folder = "D:/NEWS"
        items = [
            MediaItem("D:/MEDIA/old.mp4", "old.mp4", "video", 100),
            MediaItem("D:/NEWS/post.mp4", "post.mp4", "video", 100),
            MediaItem("D:/NEWS/post.jpg", "post.jpg", "photo", 100),
        ]
        window.all_media = items
        window.search_index = IndexedMediaLibrary(items, {})
        window.apply_filter()
        self.assertEqual(window.model.rowCount(), 1)
        with patch.object(window, "_save"), patch.object(window.preview, "_cancel_staged"):
            window.library_tabs.setCurrentIndex(1)
        self.assertEqual(window.model.rowCount(), 2)
        self.assertIn("Усього: 2", window.count.text())
        window.search.setText("post.jpg")
        window.apply_filter()
        self.assertEqual(window.model.rowCount(), 1)
        with patch.object(window, "_save"), patch.object(window.preview, "_cancel_staged"):
            window.library_tabs.setCurrentIndex(0)
        self.assertEqual(window.model.rowCount(), 1)
        self.assertEqual(window.search.text(), "")
        with patch.object(window, "_save"), patch.object(window.preview, "_cancel_staged"):
            window.library_tabs.setCurrentIndex(1)
        self.assertEqual(window.search.text(), "post.jpg")

    def test_folder_selection_persists_and_scans_without_changing_main_roots(self):
        window = self._build()
        existing_roots = window.roots[:]
        with tempfile.TemporaryDirectory() as folder, \
             patch("app.QFileDialog.getExistingDirectory", return_value=folder), \
             patch.object(window, "_save") as saved, \
             patch.object(window, "_setup_library_watcher") as watcher, \
             patch.object(window, "scan") as scanner:
            window.choose_news_folder()
            self.assertEqual(window.news_folder, folder)
            self.assertEqual(window.roots, existing_roots)
            self.assertEqual(window._scan_roots(), [folder])
            saved.assert_called_once()
            watcher.assert_called_once()
            scanner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
