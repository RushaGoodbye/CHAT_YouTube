import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from library import MediaItem, normalize_path, load_settings, save_settings
from media_collections import add_files, clean_collections, migrate_path, remove_file_references
from live_library import changed_files
from maintenance import clean_thumbnail_cache, write_diagnostics, restore_latest_backup
from streamdeck_hotkeys import ACTIONS, DEFAULT_BINDINGS, hotkey_guide


class CollectionsTests(unittest.TestCase):
    def test_multiple_playlists_reference_same_source(self):
        source = "D:/ФАКТАЖ/Путин бензин.mp4"
        collections = add_files({}, "Економіка РФ", [source, source])
        collections = add_files(collections, "Пропаганда", [source])
        self.assertEqual(len(collections["Економіка РФ"]), 1)
        self.assertEqual(len(collections["Пропаганда"]), 1)
        self.assertTrue(normalize_path(source) in collections["Пропаганда"])

    def test_move_and_delete_update_all_references(self):
        source, target = "D:/Clip 1.mp4", "D:/Медіа/Нова назва.mp4"
        data = add_files({}, "НПЗ", [source])
        data = add_files(data, "Економіка", [source])
        renamed = migrate_path(data, source, target)
        self.assertEqual(renamed["НПЗ"], [normalize_path(target)])
        self.assertEqual(renamed["Економіка"], [normalize_path(target)])
        removed = remove_file_references(renamed, [target])
        self.assertEqual(removed, {"НПЗ": [], "Економіка": []})

    def test_invalid_collections_ignored(self):
        result = clean_collections({"": ["X:/clip.mp4"],
                                    "Valid": ["D:/a.mp4", "D:/a.mp4", None],
                                    "bad\nname": ["D:/a.mp4"]})
        self.assertEqual(list(result), ["Valid"])
        self.assertEqual(len(result["Valid"]), 1)
        with self.assertRaises(ValueError):
            add_files({}, "\n", ["D:/a.mp4"])

    def test_backward_compatible_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            save_settings({"roots": [], "favorites": []}, path)
            self.assertEqual(load_settings(path)["collections"], {})
            self.assertTrue(load_settings(path)["auto_library_updates"])
            save_settings({"roots": [], "favorites": [],
                           "auto_library_updates": False,
                           "collections": add_files({}, "НПЗ", ["D:/clip.mp4"])}, path)
            got = load_settings(path)
            self.assertFalse(got["auto_library_updates"])
            self.assertEqual(got["collections"]["НПЗ"], [normalize_path("D:/clip.mp4")])


class LiveLibraryTests(unittest.TestCase):
    def test_event_add_rename_delete_only_updates_given_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            original = folder / "старий.mp4"
            original.write_bytes(b"video")
            other = folder / "другий.jpg"
            other.write_bytes(b"picture")
            before = [MediaItem(str(original), original.name, "video", 5),
                      MediaItem(str(other), other.name, "photo", 7)]
            renamed = folder / "новий.mp4"
            original.rename(renamed)
            after = changed_files(before, {str(original), str(renamed)}, [tmp])
            self.assertEqual(len(after), 2)
            self.assertTrue(any(x.name == "новий.mp4" for x in after))
            self.assertFalse(any(x.name == "старий.mp4" for x in after))
            self.assertTrue(any(x.name == "другий.jpg" for x in after))

    def test_event_outside_root_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "media"
            second = Path(tmp) / "media2"
            first.mkdir()
            second.mkdir()
            outside = second / "other.mp4"
            outside.write_bytes(b"1")
            self.assertEqual(changed_files([], {str(outside)}, [str(first)]), [])

    def test_unrelated_change_keeps_known_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp, "one.mp4")
            media.write_bytes(b"ABC")
            old = MediaItem(str(media), media.name, "video", 3)
            self.assertEqual(changed_files([old], {str(Path(tmp, "x.txt"))}, [tmp]), [old])


class MaintenanceTests(unittest.TestCase):
    def test_clean_thumbnail_cache_keeps_newest_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for i in range(5):
                f = folder / f"{i}.png"
                f.write_bytes(b"x" * 100)
                import os
                os.utime(f, (1000 + i, 1000 + i))
            unrelated = folder / "important.txt"
            unrelated.write_bytes(b"untouched")
            removed, freed = clean_thumbnail_cache(folder, max_bytes=220, max_files=3)
            self.assertEqual((removed, freed), (3, 300))
            self.assertEqual(len(list(folder.glob("*.png"))), 2)
            self.assertEqual(unrelated.read_bytes(), b"untouched")

    def test_diagnostics_does_not_pack_media_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "app.log").write_text("ERROR example", encoding="utf-8")
            (folder / "video.mp4").write_bytes(b"DO NOT ZIP")
            path = write_diagnostics(folder, version="0.4.0", file_count=4947)
            import zipfile
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), {"system_summary.json", "app.log"})

    def test_restore_backup_from_corrupt_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "settings.json")
            save_settings({"roots": ["D:/FACTAGE"], "favorites": []}, path)
            path.write_text("{BROKEN}", encoding="utf-8")
            self.assertTrue(restore_latest_backup(path))
            self.assertEqual(load_settings(path)["roots"], ["D:/FACTAGE"])


class StreamDeckHotkeysTests(unittest.TestCase):
    def test_all_five_actions_have_distinct_global_shortcuts(self):
        self.assertEqual(len(ACTIONS), 16)
        self.assertEqual(set(ACTIONS),
                         {"start", "pause", "speed_up", "speed_down", "speed_normal", "volume_down", "volume_up", "play_pause", "stop", "mute", "play_selected", "next_media", "collection_1", "collection_2", "frame_back", "frame_forward"})
        guide = hotkey_guide()
        self.assertIn("Ctrl+Alt+Shift+F6", guide)
        self.assertIn("Ctrl+Alt+Shift+F10", guide)


if __name__ == "__main__":
    unittest.main()
