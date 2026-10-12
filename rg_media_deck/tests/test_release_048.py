"""Lock in user's actual USB mini-keyboard screenshot bindings (0.4.8).

The frame shortcuts are Alt+Shift+PgDown and Alt+Shift+PgUp, NOT F18/F19.
Everything previously working (F17, F9, speed, volume) must remain identical.
"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QDialog

from streamdeck_hotkeys import (ACTIONS, BROADCAST_BINDINGS, DEFAULT_BINDINGS,
                                GlobalMediaHotkeys, check_bindings, parse_hotkey,
                                validated_bindings)
from library import load_settings, save_settings
from hotkey_dialog import HotkeyEditor


class ScreenshotBindingsTests(unittest.TestCase):
    def test_exact_pgdown_pgup_win32_scan_codes(self):
        self.assertEqual(parse_hotkey("Alt+Shift+PgDown"),
                         ("Alt+Shift+PgDown", 0x4005, 0x22))
        self.assertEqual(parse_hotkey("Alt+Shift+PgUp"),
                         ("Alt+Shift+PgUp", 0x4005, 0x21))
        self.assertEqual(parse_hotkey("alt+shift+pagedown")[0], "Alt+Shift+PgDown")
        self.assertEqual(parse_hotkey("Alt+Shift+PageUp")[0], "Alt+Shift+PgUp")
        self.assertEqual(DEFAULT_BINDINGS["frame_back"], "Alt+Shift+PgDown")
        self.assertEqual(DEFAULT_BINDINGS["frame_forward"], "Alt+Shift+PgUp")
        self.assertEqual(check_bindings(DEFAULT_BINDINGS)["frame_back"],
                         "Alt+Shift+PgDown")

    def test_exact_other_shortcuts_unchanged(self):
        expect = {
            "start": "F17", "pause": "F17",
            "speed_up": "Ctrl+Alt+Shift+=",
            "speed_down": "Ctrl+Alt+Shift+-",
            "volume_down": "Alt+Shift+-",
            "volume_up": "Alt+Shift+=",
            "mute": "F9",
            "play_pause": "Ctrl+Alt+Shift+F6",
        }
        for action, chord in expect.items():
            self.assertEqual(DEFAULT_BINDINGS[action], chord)

    def test_page_keys_require_modifier_chord(self):
        for key in ("PgUp", "PgDown", "Shift+PgUp", "Alt+PgDown",
                    "PgUp+Shift", "Win+Alt+PgDown"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_hotkey(key)

    def test_047_defaults_migrate_without_overwriting_custom_assignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            saved = dict(DEFAULT_BINDINGS)
            saved.update(frame_back="F18", frame_forward="F19")
            saved["speed_up"] = "Ctrl+Shift+Y"
            saved["stop"] = ""  # screenshot deliberately left Stop unset
            save_settings({"roots": [], "favorites": [],
                           "hotkeys_layout_version": 3,
                           "streamdeck_bindings": saved}, p)
            settings = load_settings(p)
            self.assertEqual(settings["hotkeys_layout_version"], 4)
            bindings = settings["streamdeck_bindings"]
            self.assertEqual(bindings["frame_back"], "Alt+Shift+PgDown")
            self.assertEqual(bindings["frame_forward"], "Alt+Shift+PgUp")
            self.assertEqual(bindings["speed_up"], "Ctrl+Shift+Y")
            self.assertEqual(bindings["stop"], "")
            self.assertEqual(bindings["start"], "F17")
            save_settings(settings, p)
            self.assertEqual(load_settings(p)["streamdeck_bindings"], bindings)

    def test_custom_frame_hotkeys_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            saved = dict(DEFAULT_BINDINGS)
            saved["frame_back"] = "Ctrl+Shift+Y"
            saved["frame_forward"] = "Ctrl+Shift+U"
            save_settings({"roots": [], "favorites": [],
                           "hotkeys_layout_version": 3,
                           "streamdeck_bindings": saved}, p)
            found = load_settings(p)["streamdeck_bindings"]
            self.assertEqual(found["frame_back"], "Ctrl+Shift+Y")
            self.assertEqual(found["frame_forward"], "Ctrl+Shift+U")

    def test_mini_keyboard_page_macro_registered_with_windows(self):
        if os.name != "nt":
            self.skipTest("Windows global hotkey registration")
        app = QApplication.instance() or QApplication([])
        callback = Mock()
        manager = GlobalMediaHotkeys(callback, DEFAULT_BINDINGS)
        user32 = SimpleNamespace(RegisterHotKey=Mock(return_value=True),
                                 UnregisterHotKey=Mock(return_value=True),
                                 GetAsyncKeyState=Mock(return_value=0))
        with patch("streamdeck_hotkeys.ctypes.windll", create=True,
                   new=SimpleNamespace(user32=user32)):
            try:
                manager.register()
                registered = [(call.args[2], call.args[3])
                              for call in user32.RegisterHotKey.call_args_list]
                self.assertIn((0x4005, 0x22), registered)
                self.assertIn((0x4005, 0x21), registered)
                self.assertEqual(manager._frame_routes,
                                 {0x22: "frame_back", 0x21: "frame_forward"})
            finally:
                manager.close()

    def test_bare_pagedown_does_not_trigger_global_frame_scrub(self):
        if os.name != "nt":
            self.skipTest("Windows GetAsyncKeyState")
        app = QApplication.instance() or QApplication([])
        seen = []
        manager = GlobalMediaHotkeys(seen.append, DEFAULT_BINDINGS)
        pressed = {0x22: 0x8001, 0x21: 0, 0x12: 0, 0x10: 0}
        user32 = SimpleNamespace(
            RegisterHotKey=Mock(return_value=True),
            UnregisterHotKey=Mock(return_value=True),
            GetAsyncKeyState=Mock(side_effect=lambda vk: pressed.get(vk, 0)),
        )
        with patch("streamdeck_hotkeys.ctypes.windll", create=True,
                   new=SimpleNamespace(user32=user32)):
            try:
                manager.register()
                with patch("streamdeck_hotkeys.time.monotonic", return_value=10):
                    manager._poll_frame_keys()
                self.assertFalse(seen)
                pressed[0x12] = 0x8000
                pressed[0x10] = 0x8000
                with patch("streamdeck_hotkeys.time.monotonic", return_value=10.2):
                    manager._poll_frame_keys()
                self.assertEqual(seen, ["frame_back"])
                pressed.update({0x22:0, 0x21:0x8001})
                with patch("streamdeck_hotkeys.time.monotonic", return_value=10.4):
                    manager._poll_frame_keys()
                self.assertEqual(seen, ["frame_back", "frame_forward"])
            finally:
                manager.close()


class KeyEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_picture_preset_keeps_exact_page_chords(self):
        dialog = HotkeyEditor(dict(DEFAULT_BINDINGS))
        try:
            dialog._reset_defaults()
            for action in ("frame_back", "frame_forward"):
                chord = dialog.fields[action].keySequence().toString(
                    QKeySequence.SequenceFormat.PortableText)
                self.assertEqual(parse_hotkey(chord)[0], DEFAULT_BINDINGS[action])
            dialog._save()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.bindings["frame_back"], "Alt+Shift+PgDown")
            self.assertEqual(dialog.bindings["frame_forward"], "Alt+Shift+PgUp")
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
