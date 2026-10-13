"""Local-only workspace regression tests for RG Media Deck 0.6.2."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app import MainWindow
from library import MediaItem, load_settings, save_settings
from media_search_index import IndexedMediaLibrary

class LocalWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        cfg = load_settings(Path(tempfile.gettempdir()) / "__missing_rg_local_workspace.json")
        cfg["roots"] = []
        cfg["news_folder"] = ""
        cfg["workspace_tab"] = 0
        with patch("app.load_settings", return_value=cfg), patch("app.save_settings"), patch("app.sys.argv", ["test", "--selftest"]):
            w = MainWindow()
        self.addCleanup(w.close)
        return w

    def test_only_two_tabs_and_player_side_preserves_decoder(self):
        w = self.make_window()
        self.assertEqual(w.library_tabs.count(), 2)
        self.assertEqual(w.preview_stack.count(), 1)
        player, sink = w.preview.player, w.preview.video_sink
        with patch.object(w, "_save"):
            w.set_player_side("left")
            self.assertIs(w.main_splitter.widget(0), w.player_panel)
            w.set_player_side("right")
            self.assertIs(w.main_splitter.widget(0), w.library_panel)
        self.assertIs(w.preview.player, player)
        self.assertIs(w.preview.video_sink, sink)

    def test_search_filters_both_local_libraries(self):
        w = self.make_window()
        w.news_folder = "D:/NOVYNY"
        items = [
            MediaItem("D:/Factage/Murmansk_1.mp4", "Murmansk_1.mp4", "video", 1),
            MediaItem("D:/NOVYNY/Murmansk_post.jpg", "Murmansk_post.jpg", "photo", 1),
            MediaItem("D:/NOVYNY/Other.jpg", "Other.jpg", "photo", 1),
        ]
        w.all_media = items
        w.search_index = IndexedMediaLibrary(items, {})
        original = w.preview.player
        with patch.object(w, "_save"):
            w.global_search.setText("МУРМАНСК")
            w.search_everywhere()
            self.assertEqual(w.model.rowCount(), 1)
            w.library_tabs.setCurrentIndex(1)
            self.assertEqual(w.model.rowCount(), 1)
        self.assertIs(w.preview.player, original)
        self.assertEqual(w.preview_stack.currentIndex(), 0)

    def test_queries_are_independent(self):
        w = self.make_window()
        with patch.object(w, "_save"):
            w.search.setText("кіно")
            w.library_tabs.setCurrentIndex(1)
            w.search.setText("НПЗ")
            w.library_tabs.setCurrentIndex(0)
            self.assertEqual(w.search.text(), "кіно")
            w.library_tabs.setCurrentIndex(1)
            self.assertEqual(w.search.text(), "НПЗ")

    def test_saved_side_settings_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            save_settings({"roots": [], "favorites": [], "player_side": "left"}, path)
            self.assertEqual(load_settings(path)["player_side"], "left")

if __name__ == "__main__":
    unittest.main()
