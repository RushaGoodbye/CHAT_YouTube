import tempfile
import unittest
from pathlib import Path
from library import display_media_name, MediaItem, SPEED_PRESETS, scan_media, filter_media, load_settings, save_settings, normalize_playback_rate

class LibraryTests(unittest.TestCase):
    def test_display_name_hides_only_known_media_extensions(self):
        self.assertEqual(display_media_name('Новини.2026.mp4'), 'Новини.2026')
        self.assertEqual(display_media_name('ФОТО.JPG'), 'ФОТО')
        self.assertEqual(display_media_name('recording.MKV'), 'recording')
        self.assertEqual(display_media_name('my.mov.backup'), 'my.mov.backup')
        self.assertEqual(display_media_name('strangefile'), 'strangefile')
        self.assertEqual(display_media_name('.mp4'), '.mp4')
        self.assertEqual(display_media_name('sound.mp3'), 'sound')


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

    def test_safe_selection_defaults_and_fit_modes_migrate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            save_settings({'roots': [], 'favorites': []}, path)
            settings = load_settings(path)
            self.assertTrue(settings['safe_selection'])
            self.assertEqual(settings['file_fit_modes'], {})
            save_settings({'roots': [], 'favorites': [], 'safe_selection': False,
                           'file_fit_modes': {'D:/clip.mp4': 'fill', 'invalid': 'broken'}}, path)
            settings = load_settings(path)
            self.assertFalse(settings['safe_selection'])
            self.assertEqual(settings['file_fit_modes'], {'D:/clip.mp4': 'fill'})


    def test_manual_crop_settings_validation_and_round_trip(self):
        from library import valid_manual_crops
        valid = {'D:/video.mp4': [0.12, 0.30, 0.88, 0.91],
                 'invalid': [0.9, 0.1, 0.1, 0.7],
                 'nan': [0.1, float('nan'), 0.8, 0.9],
                 'too_small': [0.2, 0.2, 0.22, 0.6]}
        self.assertEqual(valid_manual_crops(valid),
                         {'D:/video.mp4': [0.12, 0.30, 0.88, 0.91]})
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'settings.json'
            save_settings({'roots': [], 'favorites': [],
                           'file_manual_crops': valid,
                           'file_fit_modes': {'D:/video.mp4': 'manual'}}, path)
            config = load_settings(path)
            self.assertEqual(config['file_fit_modes']['D:/video.mp4'], 'manual')
            self.assertEqual(config['file_manual_crops']['D:/video.mp4'],
                             [0.12, 0.30, 0.88, 0.91])
            self.assertNotIn('invalid', config['file_manual_crops'])

if __name__ == '__main__': unittest.main()
