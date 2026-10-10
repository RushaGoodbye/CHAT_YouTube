import unittest

from PySide6.QtCore import QPoint, QRect
from hover_preview import centered_popup_position


class HoverPopupPlacementTests(unittest.TestCase):
    def test_preview_is_horizontally_centered_on_cursor(self):
        bounds = QRect(0, 0, 1920, 1080)
        point = centered_popup_position(QPoint(700, 300), bounds, 306, 270)
        self.assertEqual(point.x() + 153, 700)
        self.assertEqual(point.y(), 318)

    def test_near_left_edge_clamps_without_shifting_content(self):
        bounds = QRect(0, 0, 1920, 1080)
        point = centered_popup_position(QPoint(10, 90), bounds, 306, 270)
        self.assertEqual(point.x(), 0)

    def test_near_right_edge_clamps_inside_screen(self):
        bounds = QRect(0, 0, 1920, 1080)
        point = centered_popup_position(QPoint(1900, 90), bounds, 306, 270)
        self.assertEqual(point.x(), 1614)

    def test_bottom_edge_preview_goes_above_cursor(self):
        bounds = QRect(0, 0, 1920, 1080)
        point = centered_popup_position(QPoint(700, 1050), bounds, 306, 270)
        self.assertEqual(point.y(), 762)

    def test_negative_origin_second_monitor(self):
        bounds = QRect(-1920, -100, 1920, 1080)
        point = centered_popup_position(QPoint(-850, 500), bounds, 306, 270)
        self.assertEqual(point.x(), -1003)
        self.assertTrue(bounds.contains(point))

    def test_bad_geometry_does_not_show_popup(self):
        with self.assertRaises(ValueError):
            centered_popup_position(QPoint(1, 1), QRect(0, 0, 0, 0), 306, 270)


if __name__ == '__main__':
    unittest.main()
