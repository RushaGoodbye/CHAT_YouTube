"""Regression: mini keyboard WM_HOTKEY delivery and 0.4.3 -> 0.4.5 migration."""
import ctypes
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QApplication
from mini_keyboard_diagnostics import MiniKeyboardDiagnostics
from PySide6.QtWidgets import QApplication

from library import load_settings, save_settings
from streamdeck_hotkeys import (
    ACTIONS, DEFAULT_BINDINGS, LEGACY_BINDINGS, BROADCAST_BINDINGS,
    GlobalMediaHotkeys, MOD_NOREPEAT, WM_HOTKEY,
)


class NativeHotkeyEventTests(unittest.TestCase):
    def test_qbytearray_native_event_decodes_to_windows_message_type(self):
        # str(QByteArray) may be "b'windows_generic_MSG'": was previously
        # unconditionally rejected, so ALL keyboard shortcuts silently failed.
        for name in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            self.assertEqual(
                GlobalMediaHotkeys._native_type(QByteArray(name.encode("ascii"))),
                name)

    def test_pyqt_message_event_name_compatibility(self):
        self.assertEqual(
            GlobalMediaHotkeys._native_type("windows_generic_MSG"),
            "windows_generic_MSG")
        self.assertEqual(
            GlobalMediaHotkeys._native_type("b'windows_generic_MSG'"),
            "windows_generic_MSG")

    @unittest.skipUnless(os.name == "nt", "WM_HOTKEY delivery requires Windows")
    def test_registered_f17_hotkey_dispatches_with_actual_qbytearray(self):
        hotkey_action, diagnostic = Mock(), Mock()
        hotkeys = GlobalMediaHotkeys(hotkey_action, DEFAULT_BINDINGS)
        user = SimpleNamespace(RegisterHotKey=Mock(return_value=True),
                               UnregisterHotKey=Mock(return_value=True))
        with patch("streamdeck_hotkeys.ctypes.windll", create=True,
                   new=SimpleNamespace(user32=user)):
            hotkeys.register()
            self.assertEqual(len(hotkeys.registered), len(ACTIONS)-1)
            hotkeys.diagnostic_callback = diagnostic
            # Construct native Windows MSG with WM_HOTKEY and one registered ID
            key_id = next(k for k, v in hotkeys.registered.items() if v == "play_pause")
            msg = ctypes.wintypes.MSG()
            msg.message = WM_HOTKEY
            msg.wParam = key_id
            dispatched, result = hotkeys.nativeEventFilter(
                QByteArray(b"windows_generic_MSG"), ctypes.addressof(msg))
            self.assertTrue(dispatched)
            self.assertEqual(result, 0)
            diagnostic.assert_called_once_with("play_pause")
            hotkey_action.assert_not_called()
            hotkeys.diagnostic_callback = None
            # Second notification from the same physical press must NOT pause
            # immediately after it started playback.
            with patch("streamdeck_hotkeys.time.monotonic", return_value=200.0):
                hotkeys.nativeEventFilter(QByteArray(b"windows_generic_MSG"),
                                         ctypes.addressof(msg))
            hotkey_action.assert_not_called()
            # A later independent keypress should work.
            with patch("streamdeck_hotkeys.time.monotonic", return_value=200.250):
                hotkeys.nativeEventFilter(QByteArray(b"windows_generic_MSG"),
                                         ctypes.addressof(msg))
            hotkey_action.assert_called_once_with("play_pause")
            hotkeys.close()


class MiniKeyboardDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_diagnostic_receives_signal_without_triggering_playback(self):
        playback = Mock()
        hotkeys = GlobalMediaHotkeys(playback, DEFAULT_BINDINGS)
        hotkeys.registered_chords = {
            "start": "F17",
            "mute": "F9",
        }
        dialog = MiniKeyboardDiagnostics(hotkeys)
        try:
            self.assertIn("ЗАРЕЄСТРОВАНО", dialog.registrations.text())
            self.assertIn("НЕ ЗАРЕЄСТРОВАНО", dialog.registrations.text())
            self.assertIsNotNone(hotkeys.diagnostic_callback)
            hotkeys.diagnostic_callback("play_pause")
            self.assertIn("Play / Pause", dialog.history.toPlainText())
            playback.assert_not_called()
        finally:
            dialog.reject()
        self.assertIsNone(hotkeys.diagnostic_callback)


class SettingsMigrationVersionTests(unittest.TestCase):
    def test_old_saved_layout_version_2_gets_f17_without_losing_other_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            save_settings({
                "roots": ["D:/news"], "favorites": ["D:/news/clip.mp4"],
                "hotkeys_layout_version": 2,
                "streamdeck_bindings": dict(LEGACY_BINDINGS),
            }, path)
            result = load_settings(path)
            self.assertEqual(result["hotkeys_layout_version"], 3)
            self.assertEqual(result["favorites"], ["D:/news/clip.mp4"])
            for action, chord in BROADCAST_BINDINGS.items():
                self.assertEqual(result["streamdeck_bindings"][action], chord)
            save_settings(result, path)
            self.assertEqual(load_settings(path)["streamdeck_bindings"]["start"], "F17")

    def test_custom_hotkeys_are_preserved_during_v2_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            bindings = dict(LEGACY_BINDINGS)
            bindings["start"] = "Ctrl+Alt+Q"
            bindings["mute"] = ""
            save_settings({"roots": [], "favorites": [],
                           "hotkeys_layout_version": 2,
                           "streamdeck_bindings": bindings}, path)
            result = load_settings(path)["streamdeck_bindings"]
            self.assertEqual(result["start"], "Ctrl+Alt+Q")
            self.assertEqual(result["mute"], "")
            self.assertEqual(result["pause"], "F17")

    def test_current_layout_is_never_migrated_again(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            save_settings({"roots": [], "favorites": [],
                           "hotkeys_layout_version": 3,
                           "streamdeck_bindings": {"start": "Ctrl+Alt+F1"}},
                          path)
            result = load_settings(path)["streamdeck_bindings"]
            self.assertEqual(result["start"], "Ctrl+Alt+F1")


if __name__ == "__main__":
    unittest.main()
