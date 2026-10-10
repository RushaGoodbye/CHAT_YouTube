import unittest

from recycle_utils import normalize_recycle_path


class WindowsRecyclePathTests(unittest.TestCase):
    def test_mixed_slashes_unicode_and_spaces(self):
        path = "F:/ФАКТАЖ\\VIDEO FACTS RG/ВОЙНА пришла в рф\\06.02.204 Последствия прилёта по Белгороду-3_1.mp4"
        expected = "F:\\ФАКТАЖ\\VIDEO FACTS RG\\ВОЙНА пришла в рф\\06.02.204 Последствия прилёта по Белгороду-3_1.mp4"
        self.assertEqual(normalize_recycle_path(path), expected)
        self.assertNotIn("/", normalize_recycle_path(path))

    def test_regular_drive_path_unchanged(self):
        path = "D:\\Новости\\клип.mp4"
        self.assertEqual(normalize_recycle_path(path), path)

    def test_long_path_prefix_stripped(self):
        self.assertEqual(normalize_recycle_path("\\\\?\\F:\\Новини\\file.mp4"),
                         "F:\\Новини\\file.mp4")

    def test_unc_share(self):
        path = "\\\\NAS\\Media/Новости\\file.mp4"
        self.assertEqual(normalize_recycle_path(path),
                         "\\\\NAS\\Media\\Новости\\file.mp4")

    def test_rejects_relative_and_drive_relative_paths(self):
        for path in ("clip.mp4", "media/clip.mp4", "F:relative\\clip.mp4",
                     "\\relative-to-drive.mp4", "", " ", "F:\\"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    normalize_recycle_path(path)

    def test_rejects_device_and_null_character(self):
        for path in ("\\\\.\\PHYSICALDRIVE0", "F:\\bad\x00file.mp4"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    normalize_recycle_path(path)


if __name__ == "__main__":
    unittest.main()
