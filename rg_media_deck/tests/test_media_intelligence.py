import tempfile
import unittest
from pathlib import Path

from media_intelligence import (
    add_bookmark, clean_bookmarks, clean_tags, fold, search_match, variants,
)
from library import MediaItem, filter_media, load_settings, normalize_path, save_settings


class SmartSearchTests(unittest.TestCase):
    def test_wrong_keyboard_layout(self):
        self.assertTrue(search_match('vjcrdf', 'Москва.mp4'))
        self.assertTrue(search_match('ghbdtn', 'Привет, Москва.mp4'))
        self.assertTrue(search_match('руддщ', 'hello.mp4'))

    def test_multiple_terms_order_independent_and_folded(self):
        self.assertTrue(search_match('МИР  2026', 'Сводка_мир-2026.mp4'))
        self.assertTrue(search_match('2026 мир', 'Сводка мир 2026'))
        self.assertFalse(search_match('видео неизвестно', 'Новое видео.mp4'))
        self.assertTrue(search_match('', 'Любое название.mp4'))

    def test_tags_and_library_filter(self):
        item = MediaItem('D:/фактаж/r01.mp4', 'без названия.mp4', 'video', 125)
        key = normalize_path(item.path)
        matches = filter_media([item], 'нпз бензин', tags={key: ['НПЗ', 'Бензин']})
        self.assertEqual(matches, [item])
        self.assertEqual(filter_media([item], 'роснефть', tags={key: ['НПЗ']}), [])

    def test_clean_tags(self):
        self.assertEqual(clean_tags(['НПЗ', 'нпз', ' Бензин ', '', 1]),
                         ['НПЗ', 'Бензин'])


class TimelineBookmarksTests(unittest.TestCase):
    def test_insert_sorted_replace_near_duplicate(self):
        original = {}
        marks = add_bookmark(original, 'D:/test.mp4', 25000, 'цитата')
        marks = add_bookmark(marks, 'D:/test.mp4', 5000, 'початок')
        marks = add_bookmark(marks, 'D:/test.mp4', 25500, 'уточнення')
        self.assertEqual([m['ms'] for m in marks['D:/test.mp4']], [5000, 25500])
        self.assertEqual(original, {})
        self.assertEqual(marks['D:/test.mp4'][-1]['note'], 'уточнення')

    def test_corrupt_bookmarks_discarded(self):
        result = clean_bookmarks({
            'good': [{'ms': 100, 'note': 'початок'}, {'ms': -1}, {'ms': 'bad'},
                     {'ms': 800, 'note': 7}],
            12: [{'ms': 1}], 'bad': 'broken'})
        self.assertEqual([x['ms'] for x in result['good']], [100, 800])
        self.assertNotIn('bad', result)

    def test_old_settings_still_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            save_settings({'roots': ['D:/фактаж'], 'favorites': [], 'volume': 55}, path)
            settings = load_settings(path)
            self.assertEqual(settings['bookmarks'], {})
            self.assertEqual(settings['tags'], {})
            self.assertTrue(settings['safe_selection'])

    def test_new_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            save_settings({'roots': [], 'favorites': [], 'bookmarks': {'D:/x': [
                {'ms': 1300, 'note': 'фраза'}]}, 'tags': {'D:/x': ['Цитата']}}, path)
            settings = load_settings(path)
            self.assertEqual(settings['bookmarks']['D:/x'][0]['ms'], 1300)
            self.assertEqual(settings['tags']['D:/x'], ['Цитата'])


if __name__ == '__main__':
    unittest.main()
