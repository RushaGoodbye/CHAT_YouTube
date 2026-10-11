import unittest
from unittest.mock import patch

from library import MediaItem, filter_media, normalize_path
from media_search_index import IndexedMediaLibrary


class SearchIndexTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            MediaItem("D:/ФАКТАЖ/Москва-2026.mp4", "Москва 2026.mp4", "video", 200),
            MediaItem("D:/ФАКТАЖ/НПЗ.mp4", "Горит завод.mp4", "video", 300),
            MediaItem("D:/ФАКТАЖ/Картина.jpg", "Фотография дня.jpg", "photo", 100),
            MediaItem("D:/ФАКТАЖ/Москва.jpg", "Москва.jpeg", "photo", 100),
        ]
        self.tags = {normalize_path(self.items[1].path): ["НПЗ", "Бензин"],
                     normalize_path(self.items[2].path): ["Украина"]}
        self.index = IndexedMediaLibrary(self.items, self.tags)

    def test_same_results_as_existing_filter_for_all_modes(self):
        favorites = {normalize_path(self.items[2].path)}
        for query in ("", "МОСКВА", "vjcrdf", "нпз бензин", "фото",
                      "2026", "несуществующее", "ГОРИТ", "Украина"):
            for kind in ("all", "video", "photo"):
                for favorites_only in (False, True):
                    with self.subTest(query=query, kind=kind, favorites_only=favorites_only):
                        expected = filter_media(
                            self.items, query, kind, favorites, favorites_only, self.tags)
                        actual = self.index.filter(query, kind, favorites, favorites_only)
                        self.assertEqual(actual, expected)

    def test_index_calculated_only_on_scan_not_every_keypress(self):
        with patch("media_search_index.fold", side_effect=AssertionError("index rebuilt")):
            for query in ("мо", "моск", "москва", "vjcrdf", "НПЗ", ""):
                self.index.filter(query)
        self.assertEqual(len(self.index), len(self.items))

    def test_reindex_after_tags_change(self):
        item = self.items[1]
        self.assertEqual(self.index.filter("Цитата"), [])
        changed = {**self.tags, normalize_path(item.path): ["Цитата"]}
        updated = IndexedMediaLibrary(self.items, changed)
        self.assertEqual(updated.filter("Цитата"), [item])
        self.assertEqual(self.index.filter("Цитата"), [])

    def test_empty_index_and_big_library(self):
        self.assertEqual(IndexedMediaLibrary().filter("любой запрос"), [])
        items = [MediaItem(f"D:/archive/video{i}.mp4",
                           f"Ролик про Москву {i}.mp4", "video", i)
                 for i in range(15000)]
        idx = IndexedMediaLibrary(items)
        self.assertEqual(len(idx.filter("про Москву")), 15000)
        self.assertEqual(idx.filter("14999"), [items[14999]])
        self.assertEqual(idx.filter("zzzz_unmatched"), [])


if __name__ == "__main__":
    unittest.main()
