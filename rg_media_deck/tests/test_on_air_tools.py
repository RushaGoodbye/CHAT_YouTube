"""Live workflow additions must remain local and bounded."""
import tempfile
import unittest
from pathlib import Path
from library import MediaItem, load_settings, save_settings
from on_air_tools import remember, suggest

APP_SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

class OnAirToolsTests(unittest.TestCase):
    def test_crossed_out_controls_are_not_created(self):
        for token in ("global_search = QLineEdit", "show_staged_preview",
                      "self.quick_buttons =", "self.history_btn =", "self.suggest_btn ="):
            self.assertNotIn(token, APP_SOURCE)

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
