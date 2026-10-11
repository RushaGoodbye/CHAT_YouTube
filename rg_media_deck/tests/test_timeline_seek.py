"""Regression tests: timeline seek must work after silent preloading (0.4.2)."""
import os
import unittest
from types import SimpleNamespace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import MarkedSlider, PlayerSurface
from library import MediaItem


class _SignalSpy:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class TimelineSeekRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_already_preloaded_media_restores_duration(self):
        new = SimpleNamespace(duration=lambda: 212000, position=lambda: 32000)
        old = SimpleNamespace(duration=lambda: 59000, position=lambda: 500)
        duration, progress = _SignalSpy(), _SignalSpy()
        subject = SimpleNamespace(
            player=new, current=MediaItem("D:/test.mp4", "test.mp4", "video", 123),
            durationChanged=duration, positionChanged=progress)
        PlayerSurface._sync_player_metadata(subject, new)
        self.assertEqual(duration.values, [212000])
        self.assertEqual(progress.values, [32000])
        PlayerSurface._sync_player_metadata(subject, old)
        self.assertEqual(duration.values, [212000],
                         "Retired player must not override current seek range")

    def test_photo_or_stopped_player_does_not_expose_seek(self):
        current = SimpleNamespace(duration=lambda: 90000, position=lambda: 100)
        duration, progress = _SignalSpy(), _SignalSpy()
        subject = SimpleNamespace(
            player=current, current=None,
            durationChanged=duration, positionChanged=progress)
        PlayerSurface._sync_player_metadata(subject, current)
        subject.current = MediaItem("D:/photo.png", "photo.png", "photo", 1024)
        PlayerSurface._sync_player_metadata(subject, current)
        self.assertFalse(duration.values)
        self.assertFalse(progress.values)

    def test_click_on_timeline_seeks_to_clicked_position(self):
        slider = MarkedSlider(Qt.Orientation.Horizontal)
        slider.resize(450, 26)
        slider.setRange(0, 180000)
        slider.show()
        self.application.processEvents()
        values = []
        slider.seekRequested.connect(values.append)
        try:
            QTest.mouseClick(slider, Qt.MouseButton.LeftButton,
                             pos=QPoint(330, 13))
            self.application.processEvents()
            self.assertTrue(values, "Click must emit seek request")
            self.assertGreater(values[-1], 100000)
            self.assertLess(values[-1], 155000)
            self.assertAlmostEqual(slider.value(), values[-1], delta=100)
        finally:
            slider.close()

    def test_dragging_on_the_groove_keeps_sending_seek(self):
        slider = MarkedSlider(Qt.Orientation.Horizontal)
        slider.resize(450, 26)
        slider.setRange(0, 120000)
        slider.show()
        self.application.processEvents()
        points = []
        slider.seekRequested.connect(points.append)
        try:
            QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(250, 13))
            QTest.mouseMove(slider, QPoint(340, 13))
            QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(340, 13))
            self.assertGreaterEqual(len(points), 2)
            self.assertGreater(points[-1], points[0])
            self.assertFalse(slider.isSliderDown())
        finally:
            slider.close()

    def test_zero_duration_does_not_generate_unsafe_seek(self):
        slider = MarkedSlider(Qt.Orientation.Horizontal)
        slider.resize(300, 26)
        slider.setRange(0, 0)
        slider.show()
        self.application.processEvents()
        points = []
        slider.seekRequested.connect(points.append)
        try:
            QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(150, 13))
            self.assertEqual(points, [])
        finally:
            slider.close()


if __name__ == "__main__":
    unittest.main()
