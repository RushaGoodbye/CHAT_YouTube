"""Regression tests for NEWS-only playlist auto-advance."""
import unittest

from library import MediaItem
from news_playlist import next_news_item


def item(name, kind='video'):
    return MediaItem('/news/' + name, name, kind, 10)


class NewsPlaylistTests(unittest.TestCase):
    def test_plays_next_in_existing_sorted_order(self):
        playlist = [item('1.mp4'), item('2.mp4'), item('10.mp4')]
        self.assertEqual(next_news_item(playlist, playlist[0].path, lambda _: True), playlist[1])
        self.assertEqual(next_news_item(playlist, playlist[1].path, lambda _: True), playlist[2])

    def test_end_of_playlist_does_not_loop(self):
        playlist = [item('1.mp4'), item('2.mp4')]
        self.assertIsNone(next_news_item(playlist, playlist[-1].path, lambda _: True))

    def test_skip_missing_or_offline_files(self):
        playlist = [item('1.mp4'), item('2.mp4'), item('3.jpg', 'photo')]
        result = next_news_item(playlist, playlist[0].path,
                                lambda path: not path.endswith('2.mp4'))
        self.assertEqual(result, playlist[2])

    def test_current_not_in_playlist_never_starts_from_first(self):
        playlist = [item('1.mp4'), item('2.mp4')]
        self.assertIsNone(next_news_item(playlist, '/different.mp4', lambda _: True))

    def test_original_sequence_is_preserved(self):
        playlist = [item('10.mp4'), item('2.mp4'), item('1.mp4')]
        self.assertEqual(next_news_item(playlist, playlist[0].path, lambda _: True), playlist[1])


if __name__ == '__main__':
    unittest.main()
