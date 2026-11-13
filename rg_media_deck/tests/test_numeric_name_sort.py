"""Filename numeric-prefix ordering for RG MEDIA DECK."""
import unittest
from library import MediaItem, media_name_sort_key


def media(name):
    return MediaItem('/library/' + name, name, 'video', 1)


class NumericFilenameSortTests(unittest.TestCase):
    def test_leading_numeric_files_sort_in_number_order(self):
        files = [media(name) for name in ('10 intro.mp4', '2 outro.mp4', '1 start.mp4', '11 end.mp4', '3 middle.mp4')]
        self.assertEqual([item.name for item in sorted(files, key=media_name_sort_key)],
                         ['1 start.mp4', '2 outro.mp4', '3 middle.mp4', '10 intro.mp4', '11 end.mp4'])

    def test_non_numeric_files_follow_numbered_ones(self):
        files = [media(name) for name in ('Zebra.jpg', '10 clip.mp4', 'Alpha.png', '02 clip.mp4')]
        self.assertEqual([item.name for item in sorted(files, key=media_name_sort_key)],
                         ['02 clip.mp4', '10 clip.mp4', 'Alpha.png', 'Zebra.jpg'])

    def test_descending_order(self):
        files = [media(name) for name in ('1.mp4', '10.mp4', '2.mp4')]
        self.assertEqual([item.name for item in sorted(files, key=media_name_sort_key, reverse=True)],
                         ['10.mp4', '2.mp4', '1.mp4'])

    def test_leading_whitespace_and_zero_padding(self):
        files = [media(name) for name in ('  3 item.mp4', '002 item.mp4', '1 item.mp4')]
        self.assertEqual([item.name for item in sorted(files, key=media_name_sort_key)],
                         ['1 item.mp4', '002 item.mp4', '  3 item.mp4'])


if __name__ == '__main__':
    unittest.main()
