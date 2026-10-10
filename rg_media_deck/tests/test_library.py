import tempfile
import unittest
from pathlib import Path
from library import MediaItem, SPEED_PRESETS, scan_media, filter_media, load_settings, save_settings, normalize_playback_rate

class LibraryTests(unittest.TestCase):
    def test_scan_search_subfolders_and_ignored_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'deep').mkdir()
            (root/'deep'/'Новини_Харків.mp4').write_bytes(b'fake')
            (root/'deep'/'Photo.jpg').write_bytes(b'fake')
            (root/'deep'/'doc.docx').write_bytes(b'fake')
            found = scan_media([str(root)])
            self.assertEqual(len(found),2)
            self.assertEqual([i.name for i in filter_media(found, 'новини харків')],['Новини_Харків.mp4'])
            self.assertEqual(len(filter_media(found, '',kind='photo')),1)

    def test_settings_preserve_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'conf.json'
            settings={'roots':['D:/photos'], 'favorites':['D:/photos/aaa.jpg'],'volume':66,'muted':True,'playback_rate':1.25}
            save_settings(settings,path)
            result=load_settings(path)
            self.assertEqual(result['roots'],settings['roots'])
            self.assertEqual(result['volume'],66)
            self.assertTrue(result['muted'])
            self.assertEqual(result['playback_rate'],1.25)

    def test_speed_settings_migrate_and_are_validated(self):
        self.assertEqual(SPEED_PRESETS, (0.5,0.75,1.0,1.25,1.5,2.0))
        self.assertEqual(normalize_playback_rate(1.38),1.5)
        self.assertEqual(normalize_playback_rate(float('nan')),1.0)
        self.assertEqual(normalize_playback_rate('2'),1.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'settings.json'
            save_settings({'roots': [], 'favorites': [], 'repeat': True, 'volume': 80},path)
            data = load_settings(path)
            self.assertFalse(data['muted'])
            self.assertEqual(data['playback_rate'],1.0)

if __name__ == '__main__': unittest.main()
