"""F17/F9 and +- hotkey regression tests for exact 2026-10-12 request."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from types import SimpleNamespace

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QDialog

from hotkey_dialog import HotkeyEditor
from library import load_settings, save_settings
from streamdeck_hotkeys import (
    ACTIONS, BROADCAST_BINDINGS, DEFAULT_BINDINGS, LEGACY_BINDINGS,
    GlobalMediaHotkeys, check_bindings, hotkey_guide,
    normalized_duplicates, parse_hotkey, validated_bindings,
)


class ScreenshotChordsTest(unittest.TestCase):
    def test_exact_requested_virtual_keys_and_modifiers(self):
        requested = {
            "start": ("F17", 0x4000, 0x80),
            "pause": ("F17", 0x4000, 0x80),
            "speed_up": ("Ctrl+Alt+Shift+=", 0x4007, 0xBB),
            "speed_down": ("Ctrl+Alt+Shift+-", 0x4007, 0xBD),
            "volume_down": ("Alt+Shift+-", 0x4005, 0xBD),
            "volume_up": ("Alt+Shift+=", 0x4005, 0xBB),
            "mute": ("F9", 0x4000, 0x78),
        }
        self.assertEqual(set(requested), set(BROADCAST_BINDINGS))
        for action, expected in requested.items():
            with self.subTest(action=action):
                self.assertEqual(parse_hotkey(BROADCAST_BINDINGS[action]), expected)

    def test_qt_shift_plus_variant_uses_oem_plus(self):
        self.assertEqual(parse_hotkey("Ctrl+Alt+Shift++"),
                         parse_hotkey("Ctrl+Alt+Shift+="))
        self.assertEqual(parse_hotkey("Alt+Shift++"),
                         parse_hotkey("Alt+Shift+="))

    def test_dangerous_bare_keys_rejected(self):
        for chord in ("A", "S", "F1", "F6", "Ctrl+F1", "Alt+F1",
                      "Win+Alt+F9", "Ctrl+Alt+F25", "Ctrl+Alt+Shift+Delete"):
            with self.subTest(chord=chord), self.assertRaises(ValueError):
                parse_hotkey(chord)

    def test_shared_f17_is_only_legal_duplicate(self):
        values = check_bindings(dict(DEFAULT_BINDINGS))
        self.assertEqual(values["start"], "F17")
        self.assertEqual(values["pause"], "F17")
        registered = normalized_duplicates(values)
        self.assertEqual(registered["start"], "play_pause")
        self.assertNotIn("pause", registered)
        with self.assertRaises(ValueError):
            check_bindings({"start": "F17", "mute": "F17"})

    def test_saved_f17_pair_remains_after_validation(self):
        values = validated_bindings(dict(DEFAULT_BINDINGS))
        self.assertEqual(values["start"], values["pause"])
        self.assertEqual(values["mute"], "F9")


class ExistingSettingsMigrationTests(unittest.TestCase):
    def test_old_default_assignments_become_picture_layout(self):
        original = dict(LEGACY_BINDINGS)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "settings.json"
            save_settings({"roots": [], "favorites": [],
                           "streamdeck_bindings": original}, config)
            saved = load_settings(config)
            for action, expected in BROADCAST_BINDINGS.items():
                self.assertEqual(saved["streamdeck_bindings"][action], expected)
            self.assertEqual(saved["hotkeys_layout_version"], 4)

    def test_custom_and_disabled_assignments_never_overwritten(self):
        custom = dict(LEGACY_BINDINGS)
        custom["speed_up"] = "Ctrl+Shift+Y"
        custom["mute"] = ""
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "settings.json"
            save_settings({"roots": [], "favorites": [],
                           "streamdeck_bindings": custom}, config)
            saved = load_settings(config)["streamdeck_bindings"]
            self.assertEqual(saved["speed_up"], "Ctrl+Shift+Y")
            self.assertEqual(saved["mute"], "")
            self.assertEqual(saved["start"], "F17")

    def test_schema_two_keeps_custom_nondefault_user_chords(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "settings.json"
            save_settings({"roots": [], "favorites": [],
                           "hotkeys_layout_version": 2,
                           "streamdeck_bindings": {"start": "Ctrl+Shift+P"}}, config)
            saved = load_settings(config)["streamdeck_bindings"]
            self.assertEqual(saved["start"], "Ctrl+Shift+P")


class WindowsHotkeyRegistrationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "RegisterHotKey available on Windows")
    def test_f17_is_registered_only_once_and_routes_to_toggle(self):
        callback = Mock()
        hotkeys = GlobalMediaHotkeys(callback, DEFAULT_BINDINGS)
        fake_user32 = SimpleNamespace(
            RegisterHotKey=Mock(return_value=True),
            UnregisterHotKey=Mock(return_value=True))
        with patch("streamdeck_hotkeys.ctypes.windll", create=True,
                   new=SimpleNamespace(user32=fake_user32)):
            hotkeys.register()
            recorded = [(call.args[2], call.args[3])
                        for call in fake_user32.RegisterHotKey.call_args_list]
            self.assertEqual(recorded.count((0x4000, 0x80)), 1)
            self.assertEqual(recorded.count((0x4000, 0x78)), 1)
            self.assertIn("play_pause", hotkeys.registered.values())
            self.assertEqual(len(hotkeys.registered), len(ACTIONS)-1)
            hotkeys.close()


class QtEditorScreenshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_preset_is_presented_in_editor_and_can_save(self):
        dialog = HotkeyEditor(dict(DEFAULT_BINDINGS))
        try:
            dialog._reset_defaults()
            f17_start = dialog.fields["start"].keySequence().toString(
                QKeySequence.SequenceFormat.PortableText)
            f17_pause = dialog.fields["pause"].keySequence().toString(
                QKeySequence.SequenceFormat.PortableText)
            self.assertEqual((f17_start, f17_pause), ("F17", "F17"))
            for key in ("speed_up", "speed_down", "volume_down", "volume_up", "mute"):
                chord = dialog.fields[key].keySequence().toString(
                    QKeySequence.SequenceFormat.PortableText)
                self.assertEqual(parse_hotkey(chord), parse_hotkey(BROADCAST_BINDINGS[key]))
            dialog._save()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.bindings["start"], "F17")
            self.assertEqual(dialog.bindings["pause"], "F17")
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
