"""Regression coverage for RG Media Deck search sorting and first-seen persistence."""
import tempfile
import unittest
from pathlib import Path

from library import MediaItem, persist_first_seen, load_settings, save_settings


class MediaFirstSeenTests(unittest.TestCase):
    def test_timestamp_survives_rescans_and_offline_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'first_seen.sqlite3'
            item = MediaItem('/demo/video.mp4', 'video.mp4', 'video', 123, 0.0)
            first = persist_first_seen([item], database)[0]
            self.assertGreater(first.added_at, 0)
            self.assertEqual(persist_first_seen([item], database)[0].added_at, first.added_at)
            self.assertEqual(persist_first_seen([], database), [])
            self.assertEqual(persist_first_seen([item], database)[0].added_at, first.added_at)

    def test_new_file_gets_own_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'first_seen.sqlite3'
            a = MediaItem('/demo/a.jpg', 'a.jpg', 'photo', 20)
            b = MediaItem('/demo/b.mp3', 'b.mp3', 'video', 20)
            result = persist_first_seen([a, b], database)
            self.assertEqual(len(result), 2)
            self.assertTrue(all(item.added_at > 0 for item in result))


class SearchPreferencesTests(unittest.TestCase):
    def test_sort_filter_and_queries_survive_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            saved = load_settings(path)
            saved.update(media_sort='date_desc', media_kind='photo',
                         media_favorites_only=True,
                         media_queries=['Мурманск', 'новини'])
            save_settings(saved, path)
            loaded = load_settings(path)
            self.assertEqual(loaded['media_sort'], 'date_desc')
            self.assertEqual(loaded['media_kind'], 'photo')
            self.assertTrue(loaded['media_favorites_only'])
            self.assertEqual(loaded['media_queries'], ['Мурманск', 'новини'])

    def test_invalid_sort_defaults_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            save_settings({'roots': [], 'favorites': [], 'media_sort': 'unknown'}, path)
            self.assertEqual(load_settings(path)['media_sort'], 'name_asc')


if __name__ == '__main__':
    unittest.main()
