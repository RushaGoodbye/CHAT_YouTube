"""Live workflow additions must remain local and bounded."""
import tempfile
import unittest
from pathlib import Path
from library import MediaItem, load_settings, save_settings
from on_air_tools import remember, suggest

APP_SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

class OnAirToolsTests(unittest.TestCase):
    def test_offair_video_uses_independent_muted_player(self):
        block = APP_SOURCE.split("    def show_staged_preview(self):", 1)[1].split("    def toggle_favorite(self):", 1)[0]
        self.assertIn("QMediaPlayer(dialog)", block)
        self.assertIn("audio.setMuted(True)", block)
        self.assertIn("player.setVideoOutput(video)", block)
        self.assertNotIn("self.preview.player.setSource", block)
        self.assertNotIn("self.open_obs_safe_video", block)

    def test_history_is_recent_unique_and_bounded(self):
        data = []
        for i in range(40):
            data = remember(data, f"D:/media/{i}.mp4")
        self.assertEqual(len(data), 30)
        self.assertEqual(data[0], "D:/media/39.mp4")
        data = remember(data, "D:/media/20.mp4")
        self.assertEqual(data[0], "D:/media/20.mp4")
        self.assertEqual(len(data), 30)

    def test_typos_resolve_to_file_stems_offline(self):
        files = [MediaItem("D:/media/Murmansk.mp4", "Murmansk.mp4", "video", 1)]
        self.assertIn("Murmansk", suggest("Murmanks", files))

    def test_quick_slots_and_history_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            save_settings({"roots": [], "favorites": [],
                           "quick_slots": ["D:/media/a.mp4"],
                           "play_history": ["D:/media/b.mp4"]}, path)
            stored = load_settings(path)
            self.assertEqual(stored["quick_slots"], ["D:/media/a.mp4"])
            self.assertEqual(stored["play_history"], ["D:/media/b.mp4"])

if __name__ == "__main__":
    unittest.main()
