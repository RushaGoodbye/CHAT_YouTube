import unittest

from playback_health import DynamicCropState, PlaybackHealth
from video_fit import Crop


class DynamicCropTests(unittest.TestCase):
    def test_initial_and_periodic_sampling_are_bounded(self):
        state = DynamicCropState()
        observed = [i for i in range(1, 601) if state.next_frame()]
        self.assertEqual(observed, [6, 14, 23, 35, 48, 64, 150, 300, 450, 600])

    def test_stable_three_frames_required(self):
        state = DynamicCropState()
        inset = Crop(.2, .25, .8, .88)
        self.assertFalse(state.observe(inset))
        self.assertFalse(state.observe(inset))
        self.assertTrue(state.observe(inset))
        self.assertEqual(state.crop, inset)

    def test_single_aberrant_frame_never_changes_live_crop(self):
        state = DynamicCropState()
        a, b = Crop(.2, .25, .8, .9), Crop(.1, .1, .9, .9)
        for _ in range(3):
            state.observe(a)
        self.assertFalse(state.observe(b))
        self.assertFalse(state.observe(a))
        self.assertFalse(state.observe(a))
        self.assertEqual(state.crop, a)

    def test_stable_layout_change_updates_after_three_samples(self):
        state = DynamicCropState()
        a, b = Crop(.2, .25, .8, .9), Crop(.3, .1, .7, .95)
        for _ in range(3):
            state.observe(a)
        self.assertFalse(state.observe(b))
        self.assertFalse(state.observe(b))
        self.assertTrue(state.observe(b))
        self.assertEqual(state.crop, b)

    def test_flat_layout_returns_to_uncropped_after_three_samples(self):
        state = DynamicCropState()
        a = Crop(.25, .2, .75, .9)
        for _ in range(3):
            state.observe(a)
        self.assertFalse(state.observe(None))
        self.assertFalse(state.observe(None))
        self.assertTrue(state.observe(None))
        self.assertIsNone(state.crop)

    def test_small_changes_do_not_jitter_player(self):
        state = DynamicCropState()
        initial = Crop(.2, .21, .8, .82)
        for _ in range(3):
            state.observe(initial)
        tiny = Crop(.21, .215, .79, .815)
        for _ in range(3):
            self.assertFalse(state.observe(tiny))
        self.assertEqual(state.crop, initial)
        state.reset()
        self.assertIsNone(state.crop)
        self.assertEqual(state.frame_count, 0)


class PlaybackHealthTests(unittest.TestCase):
    def test_stalled_video_warns_once_without_forced_restart(self):
        state = PlaybackHealth()
        state.reset(0)
        self.assertFalse(state.stalled(15000, playing=True))
        self.assertTrue(state.stalled(16001, playing=True))
        self.assertFalse(state.stalled(25000, playing=True))

    def test_progress_rearms_warning(self):
        state = PlaybackHealth()
        state.reset(1000)
        state.progress(14000, 1500)
        self.assertFalse(state.stalled(29000, playing=True))
        self.assertTrue(state.stalled(30050, playing=True))
        state.progress(30200, 2400)
        self.assertFalse(state.stalled(30250, playing=True))
        self.assertTrue(state.stalled(47000, playing=True))

    def test_pause_photo_and_buffering_are_exempt(self):
        for flags in (dict(playing=False), dict(playing=True, photo=True),
                      dict(playing=True, buffering=True)):
            with self.subTest(flags=flags):
                state = PlaybackHealth()
                state.reset(100)
                self.assertFalse(state.stalled(100000, **flags))

    def test_seek_backwards_resets_watchdog_window(self):
        state = PlaybackHealth()
        state.reset(100, 30000)
        state.progress(200, 31000)
        state.progress(5000, 1000)
        self.assertFalse(state.stalled(20000, playing=True))
        self.assertTrue(state.stalled(22000, playing=True))


if __name__ == "__main__":
    unittest.main()
