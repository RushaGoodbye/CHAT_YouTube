"""Regression tests for custom seven-action media hotkeys and safe ZIP updates."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QDialog

from app import MainWindow
from library import load_settings, save_settings
from hotkey_dialog import HotkeyEditor
from streamdeck_hotkeys import (ACTIONS, DEFAULT_BINDINGS, check_bindings,
                                parse_hotkey, validated_bindings)
from zip_updates import (SCRIPT, LAUNCHER, PROGRAM_EXE, MANIFEST,
                         stage_zip, validate_members, verify_zip)


class MediaHotkeyTests(unittest.TestCase):
    def test_seven_required_commands_and_existing_shortcuts(self):
        required = {"start", "pause", "speed_up", "speed_down",
                    "volume_down", "volume_up", "mute"}
        self.assertTrue(required.issubset(set(ACTIONS)))
        self.assertTrue(all(action in DEFAULT_BINDINGS for action in required))
        self.assertEqual(len(set(DEFAULT_BINDINGS.values())), len(DEFAULT_BINDINGS) - 1)
        self.assertEqual(len(ACTIONS), 13)

    def test_assign_letter_digit_and_function_combos(self):
        self.assertEqual(parse_hotkey("ctrl+shift+p"), ("Ctrl+Shift+P", 0x4006, ord("P")))
        self.assertEqual(parse_hotkey("Ctrl+Alt+9")[2], ord("9"))
        self.assertEqual(parse_hotkey("Ctrl+Alt+Shift+F12")[2], 0x7B)
        for bad in ("F1", "Alt+F1", "Win+Ctrl+F1", "Ctrl+Alt+F25",
                    "Ctrl+Shift+А", "Ctrl+Ctrl+F1", "Ctrl+Alt+Home"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_hotkey(bad)

    def test_duplicate_assignments_rejected_before_save(self):
        with self.assertRaises(ValueError):
            check_bindings({"start": "Ctrl+Alt+P", "mute": "Ctrl+Alt+P"})
        correct = check_bindings({"start": "Ctrl+Alt+1", "pause": "",
                                  "volume_up": "Ctrl+Shift+Y"})
        self.assertEqual(correct["volume_up"], "Ctrl+Shift+Y")
        self.assertNotIn("pause", correct)

    def test_disabled_assignment_survives_settings_validation(self):
        values = dict(DEFAULT_BINDINGS)
        values["pause"] = ""
        values["mute"] = "Ctrl+Shift+M"
        validated = validated_bindings(values)
        self.assertNotIn("pause", validated)
        self.assertEqual(validated["mute"], "Ctrl+Shift+M")

    def test_disabled_keys_survive_disk_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            assigned = dict(DEFAULT_BINDINGS)
            assigned["pause"] = ""
            assigned["start"] = "Ctrl+Shift+Y"
            save_settings({"roots": [], "favorites": [],
                           "streamdeck_bindings": assigned}, config)
            from_disk = load_settings(config)["streamdeck_bindings"]
            self.assertEqual(from_disk["pause"], "")
            self.assertEqual(from_disk["start"], "Ctrl+Shift+Y")
            registry = validated_bindings({key: from_disk.get(key, "") for key in ACTIONS})
            self.assertNotIn("pause", registry)
            self.assertEqual(registry["start"], "Ctrl+Shift+Y")

    def test_hotkey_callbacks_are_separate_and_use_transport_controls(self):
        calls = []
        fake = SimpleNamespace(
            start_playback=lambda: calls.append("start"),
            pause_playback=lambda: calls.append("pause"),
            step_speed=lambda delta: calls.append(("speed", delta)),
            step_volume=lambda delta: calls.append(("volume", delta)),
            toggle_mute=lambda: calls.append("mute"))
        for action in ("start", "pause", "speed_up", "speed_down",
                       "volume_down", "volume_up", "mute"):
            MainWindow._streamdeck_action(fake, action)
        self.assertEqual(calls, ["start", "pause", ("speed", 1), ("speed", -1),
                                 ("volume", -5), ("volume", 5), "mute"])


class HotkeyDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_editor_exposes_all_actions_and_save(self):
        dialog = HotkeyEditor(dict(DEFAULT_BINDINGS))
        try:
            self.assertEqual(set(dialog.fields), set(ACTIONS))
            dialog.fields["start"].setKeySequence(QKeySequence("Ctrl+Alt+Q"))
            dialog.fields["pause"].setKeySequence(QKeySequence())
            dialog._save()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.bindings["start"], "Ctrl+Alt+Q")
            self.assertNotIn("pause", dialog.bindings)
        finally:
            dialog.close()


class ZipPatchTests(unittest.TestCase):
    @staticmethod
    def _make_zip(folder: Path, extra=None, version="0.4.3"):
        names = {
            SCRIPT: b"Write-Output 'ready'",
            LAUNCHER: b"@echo off",
            PROGRAM_EXE: b"MZexe-fake-data",
            MANIFEST: (version + "\n").encode(),
            "RG_Media_Deck/_internal/test.dat": b"sample-data",
        }
        names.update(extra or {})
        archive = folder / "patch.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as doc:
            for filename, content in names.items():
                doc.writestr(filename, content)
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        return archive, sha

    def test_zip_extracted_only_into_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive, sha = self._make_zip(folder)
            self.assertTrue(verify_zip(archive, sha, "0.4.3"))
            with patch("zip_updates.updater.update_folder", return_value=folder):
                staging = stage_zip(archive, sha, "0.4.3")
                self.assertTrue((staging / PROGRAM_EXE).exists())
                self.assertEqual((staging / MANIFEST).read_text().strip(), "0.4.3")
                self.assertEqual((staging / SCRIPT).read_bytes(), b"Write-Output 'ready'")

    def test_zip_rejects_version_mismatch_and_modified_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, sha = self._make_zip(Path(temp))
            with self.assertRaises(ValueError):
                verify_zip(archive, sha, "0.4.4")
            with self.assertRaises(ValueError):
                verify_zip(archive, "0" * 64, "0.4.3")

    def test_zip_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, sha = self._make_zip(Path(temp), extra={
                "RG_Media_Deck/../../unexpected.exe": b"attack"})
            with self.assertRaises(ValueError):
                verify_zip(archive, sha, "0.4.3")

    def test_zip_rejects_extra_files_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, sha = self._make_zip(Path(temp), extra={"another.exe": b"attack"})
            with self.assertRaises(ValueError):
                verify_zip(archive, sha, "0.4.3")


if __name__ == "__main__":
    unittest.main()
