import tempfile
import unittest
from pathlib import Path

from PIL import Image

from build_icon import generate


class WindowsAppIconTests(unittest.TestCase):
    def test_multiresolution_icon_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            ico_path, png_path = generate(temp)
            self.assertTrue(ico_path.is_file())
            self.assertTrue(png_path.is_file())
            with Image.open(ico_path) as icon:
                sizes = icon.ico.sizes()
                self.assertTrue({(16, 16), (32, 32), (48, 48),
                                 (64, 64), (128, 128), (256, 256)} <= sizes)
            with Image.open(png_path) as image:
                self.assertEqual(image.size, (512, 512))
                self.assertEqual(image.mode, "RGBA")
                # Dark corner outside rounded-square badge is transparent.
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                # Main image is opaque and has enough contrast for taskbar.
                self.assertEqual(image.getpixel((256, 300))[3], 255)


if __name__ == "__main__":
    unittest.main()
