"""Non-destructive regression against Qt Multimedia switch freezes."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from PySide6.QtCore import QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import MainWindow, PlayerSurface, ScanThread
from library import MediaItem, load_settings, save_settings
from live_library import FileIdentityIndex
from news_library import combined_roots


class SingleDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rapid_selection_does_not_open_background_decoder(self):
        surface = PlayerSurface()
        media = MediaItem("D:/not_found.mp4", "not_found.mp4", "video", 0)
        old_player, old_audio, old_sink = surface.player, surface.audio, surface.video_sink
        try:
            for i in range(500):
                surface.prepare_item(media)
                self.assertIsNone(surface._staged_player)
                self.assertIsNone(surface._staged_audio)
                self.assertIsNone(surface._staged_sink)
            self.assertIs(surface.player, old_player)
            self.assertIs(surface.audio, old_audio)
            self.assertIs(surface.video_sink, old_sink)
        finally:
            surface.shutdown()

    def test_1000_video_photo_switches_reuse_one_decoder_and_mute_old_audio(self):
        surface = PlayerSurface()
        item = MediaItem("D:/fake.mp4", "fake.mp4", "video", 10)
        photo = MediaItem("D:/fake.png", "fake.png", "photo", 10)
        current = surface.player
        audio = surface.audio
        sources = []
        class FakePlayer:
            def playbackState(self):
                from PySide6.QtMultimedia import QMediaPlayer
                return QMediaPlayer.PlaybackState.PlayingState
            def stop(self): sources.append("stop")
            def setSource(self, url): sources.append("source")
            def setPlaybackRate(self, speed): pass
            def play(self): sources.append("play")
        fake_player = FakePlayer()
        with patch("app.os.path.isfile", return_value=True), \
             patch.object(surface, "_create_player", side_effect=AssertionError("new decoder allocated")), \
             patch.object(surface.photo, "set_file", return_value=True):
            surface.player = fake_player
            try:
                for i in range(1000):
                    media = photo if i % 11 == 0 else item
                    self.assertTrue(surface.play_item(media))
                    self.assertIs(surface.player, fake_player)
                    self.assertIsNone(surface._staged_player)
                self.assertEqual(len([x for x in sources if x == "source"]), 909)
                self.assertEqual(surface._switch_count, 909)
                self.assertEqual(sources.count("play"), 909)
            finally:
                surface.player = current
                surface.audio = audio
                surface.shutdown()

    def test_4k_frame_conversion_is_throttled_before_toimage(self):
        surface = PlayerSurface()
        surface.current = MediaItem("D:/sample.mp4", "sample.mp4", "video", 10)
        frame = MagicMock()
        frame.isValid.return_value = True
        frame.width.return_value = 3840
        frame.startTime.return_value = 0
        frame.endTime.return_value = 16667
        with patch("app.time.monotonic", side_effect=[10.0, 10.014, 10.029, 10.052]):
            with patch.object(surface.video_view, "observe_frame") as present:
                for _ in range(4):
                    surface._present_video_frame(frame)
        self.assertEqual(present.call_count, 2)
        surface.shutdown()


class WorkerAndUISafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_background_scan_indexes_identity_without_calling_ui_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for i in range(55):
                (root / f"clip_{i:03}.mp4").write_bytes(b"some bytes" * 10)
            scanner = ScanThread([folder])
            yielded = []
            scanner.scanned.connect(yielded.append)
            scanner.run()  # deterministic, no thread scheduling in this test
            self.assertEqual(len(yielded[0]), 55)
            self.assertEqual(len(scanner.new_file_ids), 55)
            self.assertFalse(scanner.moved_files)

    def test_main_scan_complete_never_stats_thousands_on_gui_thread(self):
        with tempfile.TemporaryDirectory() as folder:
            from app import MainWindow
            config = load_settings(Path(folder)/"nonexistent.json")
            config["roots"] = []
            with patch("app.load_settings", return_value=config), \
                 patch("app.save_settings"), \
                 patch("app.sys.argv", ["rg-test", "--selftest"]):
                w = MainWindow()
            try:
                entries = [MediaItem(f"D:/FACTAGE/{i}.mp4", f"{i}.mp4", "video", 10)
                           for i in range(1400)]
                mock_worker = SimpleNamespace(
                    new_file_ids={(1,i):entries[i].path for i in range(len(entries))},
                    moved_files=[])
                w.scanner = mock_worker
                with patch.object(FileIdentityIndex, "identity",
                                  side_effect=AssertionError("UI did NAS stat")), \
                     patch.object(w, "_setup_library_watcher"), \
                     patch.object(w, "_save"):
                    w.scan_complete(entries)
                self.assertEqual(len(w.all_media), 1400)
                self.assertEqual(len(w._file_identities.by_id), 1400)
            finally:
                w.scanner = None
                w.close()

    def test_video_switch_requests_within_250ms_coalesce(self):
        from app import MainWindow
        with tempfile.TemporaryDirectory() as folder:
            config = load_settings(Path(folder)/"no.json")
            config["roots"] = []
            with patch("app.load_settings", return_value=config), \
                 patch("app.save_settings"), \
                 patch("app.sys.argv", ["rg-test", "--selftest"]):
                w = MainWindow()
            try:
                w._last_switch_accepted_ms = time.monotonic() * 1000
                w.preview.current = MediaItem("D:/current.mp4", "current.mp4", "video", 10)
                first = MediaItem("D:/first.mp4", "first.mp4", "video", 10)
                last = MediaItem("D:/last.mp4", "last.mp4", "video", 10)
                with patch.object(w, "_play_selected_now") as open_media:
                    w.selected = first
                    w.play_selected()
                    w.selected = last
                    w.play_selected()
                    self.assertTrue(w._switch_timer.isActive())
                    open_media.assert_not_called()
                    w._flush_pending_switch()
                    self.assertIs(w.selected, last)
                    open_media.assert_called_once()
                    w.stop_playback()
                    self.assertIsNone(w._pending_switch_item)
                    self.assertFalse(w._switch_timer.isActive())
            finally:
                w.close()

    def test_nested_news_root_does_not_double_subscribe_watcher(self):
        base = ["D:/FACTAGE", "E:/OTHER"]
        self.assertEqual(combined_roots(base, "D:/FACTAGE/News"), base)
        self.assertEqual(combined_roots(["D:/FACTAGE/News"], "D:/FACTAGE"),
                         ["D:/FACTAGE"])
        self.assertEqual(combined_roots(base, "C:/NEWS"), base + ["C:/NEWS"])


if __name__ == "__main__":
    unittest.main()
