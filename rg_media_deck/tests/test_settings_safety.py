import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from library import load_settings, save_settings
from settings_safety import (
    backup_dir, backup_settings_once_daily, recover_settings_from_backup,
)


class SettingsBackupTests(unittest.TestCase):
    def test_corrupt_primary_recovers_previous_valid_settings(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            info = {"roots": ["D:/ФАКТАЖ"], "favorites": ["D:/test.mp4"],
                    "bookmarks": {"D:/test.mp4": [{"ms": 400, "note": "Фраза"}]}}
            save_settings(info, path)
            copies = list(backup_dir(path).glob("settings_????-??-??.json"))
            self.assertEqual(len(copies), 1)
            path.write_text("{broken data", encoding="utf-8")
            restored = load_settings(path)
            self.assertEqual(restored["roots"], ["D:/ФАКТАЖ"])
            self.assertEqual(restored["favorites"], ["D:/test.mp4"])
            self.assertEqual(restored["bookmarks"]["D:/test.mp4"][0]["ms"], 400)

    def test_daily_snapshots_do_not_copy_on_every_slider_change(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            save_settings({"roots": [], "favorites": [], "volume": 80}, path)
            snapshot = next(backup_dir(path).glob("*.json"))
            first_content = snapshot.read_bytes()
            for volume in range(100):
                save_settings({"roots": [], "favorites": [], "volume": volume}, path)
            self.assertEqual(len(list(backup_dir(path).glob("*.json"))), 1)
            self.assertEqual(snapshot.read_bytes(), first_content)
            self.assertEqual(load_settings(path)["volume"], 99)

    def test_only_last_seven_days_retained(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            path.write_text(json.dumps({"roots": [], "favorites": []}), encoding="utf-8")
            start = date(2026, 10, 1)
            for day in range(11):
                backup_settings_once_daily(path, start + timedelta(days=day))
            copies = sorted(backup_dir(path).glob("*.json"))
            self.assertEqual(len(copies), 7)
            self.assertEqual(copies[0].name, "settings_2026-10-05.json")

    def test_corrupt_latest_backup_uses_older_valid_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            path.write_text(json.dumps({"roots": ["D:/safe"], "favorites": []}), encoding="utf-8")
            backup_settings_once_daily(path, date(2026, 10, 8))
            (backup_dir(path) / "settings_2026-10-09.json").write_text("{invalid", encoding="utf-8")
            path.write_text("not valid JSON", encoding="utf-8")
            self.assertEqual(recover_settings_from_backup(path)["roots"], ["D:/safe"])


if __name__ == "__main__":
    unittest.main()
