"""F17 mini-keyboard press deduplication and global polling regression tests."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer

from app import MainWindow
from f17_press import F17PressGate
from streamdeck_hotkeys import DEFAULT_BINDINGS, GlobalMediaHotkeys


class F17PressGateTests(unittest.TestCase):
    def test_one_physical_press_one_toggle_until_release(self):
        gate = F17PressGate()
        self.assertTrue(gate.observe(down=True, pressed_since_poll=True, now_ms=1000))
        self.assertFalse(gate.observe(down=True, pressed_since_poll=False, now_ms=1030))
        self.assertFalse(gate.native_hotkey(1040))
        self.assertFalse(gate.observe(down=False, pressed_since_poll=False, now_ms=1080))
        self.assertTrue(gate.observe(down=True, pressed_since_poll=True, now_ms=1200))
        self.assertFalse(gate.native_hotkey(1210))

    def test_macro_tap_which_ends_between_polls_is_detected(self):
        gate = F17PressGate()
        self.assertTrue(gate.observe(down=False, pressed_since_poll=True, now_ms=1000))
        self.assertFalse(gate.observe(down=False, pressed_since_poll=False, now_ms=1020))
        self.assertFalse(gate.observe(down=False, pressed_since_poll=True, now_ms=1070))
        self.assertTrue(gate.observe(down=False, pressed_since_poll=True, now_ms=1210))

    def test_native_first_poll_second_is_not_duplicate(self):
        gate = F17PressGate()
        self.assertTrue(gate.native_hotkey(1000))
        self.assertFalse(gate.observe(down=True, pressed_since_poll=True, now_ms=1020))
        self.assertFalse(gate.observe(down=False, pressed_since_poll=False, now_ms=1090))
        self.assertTrue(gate.native_hotkey(1190))


class F17PollIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @unittest.skipUnless(os.name == "nt", "Windows GetAsyncKeyState only")
    def test_short_f17_global_pulse_triggers_one_start_pause(self):
        callback = Mock()
        manager = GlobalMediaHotkeys(callback, dict(DEFAULT_BINDINGS))
        user32 = SimpleNamespace(
            RegisterHotKey=Mock(return_value=False),
            UnregisterHotKey=Mock(return_value=True),
            GetAsyncKeyState=Mock(side_effect=[0x8001, 0x8000, 0, 0x0001, 0x0001]),
        )
        with patch("streamdeck_hotkeys.ctypes.windll", create=True,
                   new=SimpleNamespace(user32=user32)):
            with patch("streamdeck_hotkeys.time.monotonic",
                       side_effect=[1.0, 1.012, 1.030, 1.300, 1.315]):
                try:
                    manager.register()  # OS refused F17; polling remains available
                    self.assertEqual(manager._f17_route, "play_pause")
                    for _ in range(5):
                        manager._poll_f17()
                finally:
                    manager.close()
        self.assertEqual(callback.call_count, 2)
        callback.assert_called_with("play_pause")
        self.assertEqual(manager.f17_poll_count, 5)

    def test_f17_start_pause_behavior_uses_existing_controls(self):
        call_log = []
        play = SimpleNamespace(
            playbackState=lambda: QMediaPlayer.PlaybackState.PausedState,
            play=lambda: call_log.append("play"))
        screen = SimpleNamespace(
            preview=SimpleNamespace(player=play,
                                    current=SimpleNamespace(kind="video")),
            pause_playback=lambda: call_log.append("pause"),
            _update_play_button=lambda: call_log.append("button"))
        MainWindow.toggle_preview(screen)
        self.assertEqual(call_log, ["play", "button"])
        play.playbackState = lambda: QMediaPlayer.PlaybackState.PlayingState
        MainWindow.toggle_preview(screen)
        self.assertEqual(call_log[-1], "pause")

    def test_f17_from_blank_screen_starts_selected_file(self):
        calls = []
        screen = SimpleNamespace(
            preview=SimpleNamespace(player=None, current=None),
            play_selected=lambda: calls.append("start"))
        MainWindow.toggle_preview(screen)
        self.assertEqual(calls, ["start"])


if __name__ == "__main__":
    unittest.main()
