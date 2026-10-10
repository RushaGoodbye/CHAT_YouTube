import unittest
from video_fit import Crop, detect_letterbox, stable_crop, video_geometry, fitted_frame_rect, fill_frame_crop


def rectangle_mask(w=192, h=108, x0=67, y0=9, x1=125, y1=101):
    return [[(x0 <= x < x1 and y0 <= y < y1) for x in range(w)] for y in range(h)]


class VideoFitTests(unittest.TestCase):
    def test_crop_embedded_portrait_with_black_mattes(self):
        rect = detect_letterbox(rectangle_mask())
        self.assertIsNotNone(rect)
        self.assertLess(rect.left, 0.37)
        self.assertGreater(rect.right, 0.63)
        self.assertLess(rect.top, 0.10)
        self.assertGreater(rect.bottom, 0.91)
        self.assertLess(rect.width, 0.36)

    def test_uncropped_regular_portrait_or_landscape(self):
        self.assertIsNone(detect_letterbox(rectangle_mask(x0=2,y0=2,x1=190,y1=106)))
        self.assertIsNone(detect_letterbox([[False]*192 for _ in range(108)]))

    def test_detect_requires_bilateral_bars(self):
        self.assertIsNone(detect_letterbox(rectangle_mask(x0=8,y0=1,x1=192,y1=108)))

    def test_stable_detection_must_agree_three_times(self):
        a = Crop(0.30,0.10,0.70,0.90)
        b = Crop(0.31,0.10,0.69,0.90)
        c = Crop(0.30,0.11,0.70,0.91)
        self.assertEqual(stable_crop([a,b,c]), Crop(0.30,0.10,0.70,0.90))
        self.assertIsNone(stable_crop([a,b,None]))
        self.assertIsNone(stable_crop([a,b,Crop(0.1,0.1,0.9,0.9)]))

    def test_automatic_zoom_fits_portrait_to_viewport_height(self):
        crop = Crop(0.35,0.05,0.65,0.95)
        x,y,w,h = video_geometry(900,660,1920,1080,crop)
        displayed_height = h*crop.height
        self.assertAlmostEqual(displayed_height,660,delta=2)
        self.assertLess(x,0)
        self.assertGreater(w,900)
        self.assertLess(y,10)

    def test_automatic_crop_cannot_resize_viewport(self):
        target, source = fitted_frame_rect(900, 660, 1920, 1080, Crop(0.35, 0.05, 0.65, 0.95))
        x, y, w, h = target
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x+w, 900.0001)
        self.assertLessEqual(y+h, 660.0001)
        self.assertAlmostEqual(h, 660)
        self.assertAlmostEqual(w/h, source[2]/source[3], places=8)

    def test_landscape_aspect_fit_is_bounded(self):
        target, source = fitted_frame_rect(800, 500, 1920, 1080)
        self.assertEqual(source, (0, 0, 1920, 1080))
        self.assertAlmostEqual(target[2], 800)
        self.assertLess(target[3], 500)

    def test_portrait_uses_full_height_without_widget_growth(self):
        target, source = fitted_frame_rect(900, 660, 1080, 1920)
        self.assertAlmostEqual(target[3], 660)
        self.assertLess(target[2], 900)
        self.assertAlmostEqual(target[0] * 2 + target[2], 900)

    def test_safe_geometry_when_view_hidden(self):
        self.assertEqual(video_geometry(0,0,1920,1080,Crop(0.25,0,0.75,1)),(0,0,1,1))


    def test_fill_crop_is_bounded_and_fills_viewport(self):
        rect = fill_frame_crop(900, 660, 1920, 1080)
        target, source = fitted_frame_rect(900, 660, 1920, 1080, rect)
        self.assertAlmostEqual(target[2], 900)
        self.assertAlmostEqual(target[3], 660)
        self.assertGreaterEqual(source[0], 0)
        self.assertLessEqual(source[0] + source[2], 1920.0001)

    def test_portrait_fill_center_crops_vertically(self):
        rect = fill_frame_crop(1000, 400, 1080, 1920)
        target, _ = fitted_frame_rect(1000, 400, 1080, 1920, rect)
        self.assertAlmostEqual(target[2], 1000)
        self.assertAlmostEqual(target[3], 400)

if __name__ == '__main__':
    unittest.main()
