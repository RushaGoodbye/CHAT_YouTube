"""Frame-by-frame mini keyboard regression (F18/F19) for RG Media Deck 0.4.7."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer

from frame_seek import FrameSeekPlanner
from streamdeck_hotkeys import (
    DEFAULT_BINDINGS, ACTIONS, GlobalMediaHotkeys, check_bindings,
    parse_hotkey)
from app import MainWindow


class FrameTimestampSeekTests(unittest.TestCase):
    def test_default_25fps_moves_40ms_from_stopped_cursor(self):
        seek = FrameSeekPlanner()
        self.assertEqual(seek.step(1, 1000, 5000), 1040)
        self.assertEqual(seek.step(1, 1000, 5000), 1080)
        self.assertEqual(seek.step(-1, 1000, 5000), 1040)

    def test_real_25fps_pts_used_not_fabricated_seconds(self):
        seek = FrameSeekPlanner()
        for pts in (960, 1000, 1040, 1080):
            seek.observe(pts * 1000, (pts + 40) * 1000)
        self.assertAlmostEqual(seek.frame_ms, 40)
        self.assertEqual(seek.step(-1, 1002, 5000), 960)
        seek.sync_external_seek()
        self.assertEqual(seek.step(1, 1001, 5000), 1040)

    def test_2997_fps_and_60fps(self):
        seek = FrameSeekPlanner()
        seek.set_fps(29.97)
        self.assertEqual(seek.step(1, 1000, 5000), 1033)
        self.assertEqual(seek.step(1, 1000, 5000), 1067)
        self.assertEqual(seek.step(1, 1000, 5000), 1100)
        seek.reset()
        seek.set_fps(60)
        self.assertEqual(seek.step(1, 2000, 5000), 2017)

    def test_variable_fps_neighbor_pts_takes_precedence(self):
        seek = FrameSeekPlanner()
        for a, b in ((900, 924), (924, 957), (957, 982),
                     (982, 1016), (1016, 1040)):
            seek.observe(a * 1000, b * 1000)
        self.assertEqual(seek.step(1, 982, 5000), 1016)
        self.assertEqual(seek.step(-1, 982, 5000), 982)

    def test_edges_never_seek_outside_media(self):
        seek = FrameSeekPlanner()
        self.assertEqual(seek.step(-1, 1, 100), 0)
        self.assertEqual(seek.step(-1, 0, 100), 0)
        seek.sync_external_seek()
        self.assertEqual(seek.step(1, 99, 100), 100)

    def test_reset_discards_previous_video_pts_and_cursor(self):
        seek = FrameSeekPlanner()
        seek.observe(100000, 140000)
        seek.set_fps(50)
        seek.step(1, 100, 2000)
        seek.reset()
        self.assertEqual(seek.fps, 0)
        self.assertEqual(len(seek.timestamps_ms), 0)
        self.assertIsNone(seek.cursor_ms)
        self.assertEqual(seek.step(1, 200, 2000), 240)


class FrameShortcutTests(unittest.TestCase):
    def test_pictured_pgdown_pgup_defaults_and_f17_f9_unchanged(self):
        self.assertEqual(DEFAULT_BINDINGS["frame_back"], "Alt+Shift+PgDown")
        self.assertEqual(DEFAULT_BINDINGS["frame_forward"], "Alt+Shift+PgUp")
        self.assertEqual(DEFAULT_BINDINGS["start"], "F17")
        self.assertEqual(DEFAULT_BINDINGS["pause"], "F17")
        self.assertEqual(DEFAULT_BINDINGS["mute"], "F9")
        self.assertEqual(parse_hotkey("F18"), ("F18", 0x4000, 0x81))
        self.assertEqual(parse_hotkey("F19"), ("F19", 0x4000, 0x82))
        self.assertEqual(len(ACTIONS), 15)
        self.assertEqual(check_bindings(DEFAULT_BINDINGS)["frame_back"], "Alt+Shift+PgDown")

    def test_action_routing_not_confused_with_ordinary_seek(self):
        calls = []
        screen = SimpleNamespace(step_frame=lambda delta: calls.append(delta))
        MainWindow._streamdeck_action(screen, "frame_back")
        MainWindow._streamdeck_action(screen, "frame_forward")
        self.assertEqual(calls, [-1, 1])

    def test_fps_steps_leave_paused_and_do_not_create_audio(self):
        actions = []
        class Player:
            def playbackState(self): return QMediaPlayer.PlaybackState.PlayingState
            def pause(self): actions.append("pause")
            def setPosition(self, pos): actions.append(("seek", pos))
        player = Player()
        item = SimpleNamespace(kind="video", path="D:/example.mp4")
        fake_preview = SimpleNamespace(player=player, current=item,
                                       frame_step_target=lambda d: (960 if d < 0 else 1040, 40.0))
        screen = SimpleNamespace(
            preview=fake_preview,
            status=SimpleNamespace(setText=lambda value: actions.append(("status", value))),
            _update_play_button=lambda: actions.append("paint"))
        def immediate(_delay, callback):
            callback()
        with patch("app.QTimer.singleShot", side_effect=immediate):
            MainWindow.step_frame(screen, -1)
        self.assertEqual(actions[0], "pause")
        self.assertIn(("seek", 960), actions)
        self.assertNotIn("play", actions)

    @unittest.skipUnless(os.name == 'nt', "Windows GetAsyncKeyState only")
    def test_f18_and_f19_short_hid_pulses(self):
        app = QApplication.instance() or QApplication([])
        called = []
        # Custom legacy F18/F19 mappings must remain functional.
        legacy = dict(DEFAULT_BINDINGS)
        legacy.update(frame_back="F18", frame_forward="F19")
        manager = GlobalMediaHotkeys(called.append, legacy)
        user32 = SimpleNamespace(
            RegisterHotKey=Mock(return_value=False),
            UnregisterHotKey=Mock(return_value=True),
            GetAsyncKeyState=Mock(side_effect=[
                0x8001, 0x0000,
                0x0000, 0x0000,
                0x0000, 0x8001,
                0x0000, 0x0000,
            ]))
        with patch("streamdeck_hotkeys.ctypes.windll", create=True,
                   new=SimpleNamespace(user32=user32)):
            try:
                manager.register()
                self.assertEqual(manager._frame_routes,
                                 {0x81: "frame_back", 0x82: "frame_forward"})
                with patch("streamdeck_hotkeys.time.monotonic",
                           side_effect=[10.0, 10.025, 10.250, 10.280]):
                    for _ in range(4):
                        manager._poll_frame_keys()
            finally:
                manager.close()
        self.assertEqual(called, ["frame_back", "frame_forward"])


if __name__ == "__main__":
    unittest.main()
