import unittest

from content_region import detect_content_region
from video_fit import fitted_frame_rect, stable_crop


def composited_frame(w=192, h=108, rectangle=(35, 40, 167, 99),
                     titles=True):
    picture = [[(0, 0, 0) for _ in range(w)] for _ in range(h)]
    x0, y0, x1, y1 = rectangle
    for y in range(y0, y1):
        for x in range(x0, x1):
            picture[y][x] = ((x * 7 + y * 5) % 120 + 80,
                             (x * 3 + y * 7) % 150 + 60,
                             (x * 11 + y * 9) % 130 + 55)
    if titles:
        for y in range(5, 11):
            for x in range(65, 145):
                picture[y][x] = (240, 240, 240)
        for y in range(22, 28):
            for x in range(76, 120):
                picture[y][x] = (180, 170, 100)
    return picture


class ActiveContentTests(unittest.TestCase):
    def test_embedded_footage_with_decorative_title_and_caption(self):
        detected = detect_content_region(composited_frame())
        self.assertIsNotNone(detected)
        self.assertLess(abs(detected.left - 35/192), .035)
        self.assertLess(abs(detected.top - 40/108), .045)
        self.assertLess(abs(detected.right - 167/192), .035)
        self.assertLess(abs(detected.bottom - 99/108), .045)
        self.assertLess(detected.height, 0.65)

    def test_fixed_player_geometry(self):
        candidate = detect_content_region(composited_frame())
        target, source = fitted_frame_rect(900, 660, 1920, 1080, candidate)
        self.assertGreater(source[0], 0)
        self.assertGreater(source[1], 0)
        self.assertGreaterEqual(target[0], 0)
        self.assertGreaterEqual(target[1], 0)
        self.assertLessEqual(target[0] + target[2], 900.0001)
        self.assertLessEqual(target[1] + target[3], 660.0001)

    def test_does_not_crop_regular_full_frame_picture(self):
        photo = [[((x * 11 + y) % 255, (y * 8 + 40) % 255,
                    (x * 3 + y * 9) % 255) for x in range(192)]
                 for y in range(108)]
        self.assertIsNone(detect_content_region(photo))

    def test_only_title_no_video(self):
        image = [[(0, 0, 0) for _ in range(192)] for _ in range(108)]
        for y in range(6, 17):
            for x in range(65, 145):
                image[y][x] = (255, 255, 255)
        self.assertIsNone(detect_content_region(image))

    def test_temporal_confirmation_blocks_flashes(self):
        sample = detect_content_region(composited_frame())
        self.assertIsNone(stable_crop([sample, None, sample]))
        self.assertEqual(stable_crop([sample, sample, sample]), sample)

    def test_invalid_frames_are_skipped(self):
        self.assertIsNone(detect_content_region([]))
        self.assertIsNone(detect_content_region([[(0, 0, 0)] * 100] * 5))
        self.assertIsNone(detect_content_region([[(0, 0, 0)] * 192] * 107 +
                                                [[(0, 0, 0)] * 190]))



    def test_vertical_inset_on_black_mattee(self):
        img = composited_frame(rectangle=(67, 4, 126, 105), titles=False)
        crop = detect_content_region(img)
        self.assertIsNotNone(crop)
        self.assertLess(crop.width, 0.37)
        target, _ = fitted_frame_rect(900, 660, 1920, 1080, crop)
        self.assertAlmostEqual(target[3], 660, delta=1.0)

    def test_noise_near_corners_rejects_uncertain_inset(self):
        frame = composited_frame()
        for y in range(9):
            for x in range(17):
                frame[y][x] = (x * 10 % 255, y * 12 % 255, 120)
        self.assertIsNone(detect_content_region(frame))

if __name__ == '__main__':
    unittest.main()
