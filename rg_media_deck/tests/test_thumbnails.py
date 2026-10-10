import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QImage, QColor
from thumbnails import make_thumbnail, thumbnail_path


class ThumbnailsTests(unittest.TestCase):
    def test_photo_thumbnail_cached_without_modifying_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'Оригінал фото.png'
            image = QImage(900, 500, QImage.Format.Format_RGB32)
            image.fill(QColor('#559977'))
            self.assertTrue(image.save(str(source), 'PNG'))
            with patch('thumbnails.settings_path', return_value=folder / 'settings.json'):
                first = make_thumbnail(str(source), 'photo')
                self.assertIsNotNone(first)
                self.assertTrue(first.is_file())
                self.assertLess(first.stat().st_size, source.stat().st_size)
                self.assertEqual(make_thumbnail(str(source), 'photo'), first)

    def test_missing_media_does_not_create_thumbnail(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(make_thumbnail(str(Path(tmp) / 'missing.mp4'), 'video'))


if __name__ == '__main__':
    unittest.main()
