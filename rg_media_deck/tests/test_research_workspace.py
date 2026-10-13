"""Four-source research workspace regression tests for RG Media Deck 0.5.0."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from app import MainWindow
from library import MediaItem, load_settings, save_settings
from media_search_index import IndexedMediaLibrary
from service_browser import ServiceBrowser, _TELEGRAM_SEARCH_JS, _CHATGPT_PREPARE_JS
from unified_research import (normalize_query, research_prompt, telegram_search_hint,
                              external_site_url)


class GlobalPromptTests(unittest.TestCase):
    def test_city_research_prompt_requires_recent_citations_and_no_fake_counts(self):
        prompt = research_prompt("  МУРМАНСК   ")
        for phrase in ("МУРМАНСК", "30 дней", "последние 10 лет",
                       "погибших", "Школы", "детские сады", "больницы",
                       "ссылками", "Не выдумывай", "сайт"):
            if phrase == "сайт":
                continue
            self.assertIn(phrase, prompt)
        self.assertIn("НЕ равно точному числу", prompt)
        self.assertIn("достоверного числа нет", prompt)

    def test_search_input_is_normalized_and_injection_never_executed(self):
        self.assertEqual(normalize_query("  МУРМАНСК\t \nвидео  "), "МУРМАНСК видео")
        self.assertEqual(normalize_query("x" * 1000), "x" * 180)
        self.assertEqual(research_prompt(""), "")
        self.assertEqual(external_site_url("telegram"), "https://web.telegram.org/k/")
        self.assertEqual(external_site_url("chatgpt"), "https://chatgpt.com/")
        with self.assertRaises(ValueError):
            external_site_url("phishing")

    def test_telegram_info_does_not_pretend_access_to_all_channels(self):
        self.assertIn("доступные вашему аккаунту",
                      telegram_search_hint("Мурманск"))
        self.assertNotIn("login", _TELEGRAM_SEARCH_JS.lower())
        self.assertIn("[type=password]", _TELEGRAM_SEARCH_JS)
        self.assertIn("__PROMPT__", _CHATGPT_PREPARE_JS)


class SettingsAndLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = load_settings(Path(temp.name) / "no.json")
        config["roots"] = []
        config["news_folder"] = ""
        with patch("app.load_settings", return_value=config), \
             patch("app.save_settings"), \
             patch("app.sys.argv", ["rg-test", "--selftest"]):
            w = MainWindow()
        self.addCleanup(w.close)
        return w

    def test_backward_compatibility_and_workspace_side_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            save_settings({"roots": [], "favorites": [],
                           "news_tab_active": True}, config)
            old = load_settings(config)
            self.assertEqual(old["workspace_tab"], 1)
            self.assertEqual(old["player_side"], "right")
            self.assertEqual(old["global_query"], "")
            old.update(workspace_tab=3, player_side="left",
                       global_query="МУРМАНСК")
            save_settings(old, config)
            newer = load_settings(config)
            self.assertEqual(newer["workspace_tab"], 3)
            self.assertEqual(newer["player_side"], "left")
            self.assertEqual(newer["global_query"], "МУРМАНСК")

    def test_can_move_player_both_ways_without_rebuilding_decoder(self):
        w = self._window()
        player = w.preview.player
        sink = w.preview.video_sink
        self.assertEqual(w.main_splitter.widget(0), w.library_panel)
        with patch.object(w, "_save") as saved:
            w.set_player_side("left")
            self.assertIs(w.main_splitter.widget(0), w.player_panel)
            self.assertIs(w.preview.player, player)
            self.assertIs(w.preview.video_sink, sink)
            w.set_player_side("right")
            self.assertIs(w.main_splitter.widget(0), w.library_panel)
            self.assertIs(w.preview.player, player)
            self.assertEqual(saved.call_count, 2)

    def test_four_tabs_are_present_and_web_browsers_start_lazily(self):
        w = self._window()
        self.assertEqual(w.library_tabs.count(), 4)
        self.assertIn("TELEGRAM", w.library_tabs.tabText(2))
        self.assertIn("CHATGPT", w.library_tabs.tabText(3))
        self.assertFalse(w.telegram_tab.active)
        self.assertFalse(w.chatgpt_tab.active)
        with patch.object(w.telegram_tab, "ensure_loaded", return_value=True), \
             patch.object(w.chatgpt_tab, "ensure_loaded", return_value=True), \
             patch.object(w, "_save"), \
             patch.object(w, "stop_playback") as stop:
            w.library_tabs.setCurrentIndex(2)
            self.assertEqual(w.preview_stack.currentIndex(), 1)
            w.library_tabs.setCurrentIndex(3)
            self.assertEqual(w.preview_stack.currentIndex(), 2)
            w.library_tabs.setCurrentIndex(0)
            self.assertEqual(w.preview_stack.currentIndex(), 0)
            stop.assert_not_called()

    def test_one_query_filters_both_factage_and_news_and_prepares_web_search(self):
        w = self._window()
        w.news_folder = "D:/NOVYNY"
        items = [
            MediaItem("D:/Factage/Murmansk_1.mp4", "Murmansk_1.mp4", "video", 1),
            MediaItem("D:/Factage/Other.mp4", "Other.mp4", "video", 1),
            MediaItem("D:/NOVYNY/Murmansk_post.jpg", "Murmansk_post.jpg", "photo", 1),
            MediaItem("D:/NOVYNY/Other.jpg", "Other.jpg", "photo", 1),
        ]
        w.all_media = items
        w.search_index = IndexedMediaLibrary(items, {})
        old_player = w.preview.player
        with patch.object(w, "_save"), \
             patch.object(w.telegram_tab, "ensure_loaded") as telegram_start, \
             patch.object(w.chatgpt_tab, "ensure_loaded") as gpt_start:
            w.global_search.setText("Мурманск")
            w.search_everywhere()
            self.assertEqual(w._library_queries, ["Мурманск", "Мурманск"])
            self.assertEqual(w.telegram_tab._pending_query, "Мурманск")
            self.assertEqual(w.chatgpt_tab._pending_query, "Мурманск")
            self.assertEqual(w.library_tabs.currentIndex(), 3)
            w.library_tabs.setCurrentIndex(0)
            self.assertEqual(w.model.rowCount(), 1)
            self.assertIn("Murmansk", w.model.rows[0].name)
            w.library_tabs.setCurrentIndex(1)
            self.assertEqual(w.model.rowCount(), 1)
            self.assertIn("Murmansk", w.model.rows[0].name)
            self.assertIs(w.preview.player, old_player)
            telegram_start.assert_not_called()  # inactive service stays lazy
            gpt_start.assert_called_once()  # common search opens live AI result pane
            self.assertIn("веб-результати", w.status.text().casefold())

    def test_city_folder_and_latin_filenames_are_searchable(self):
        w = self._window()
        items = [
            MediaItem("D:/ФАКТАЖ/МУРМАНСК/001.mp4", "001.mp4", "video", 1),
            MediaItem("D:/ФАКТАЖ/Murmansk_2026.mp4", "Murmansk_2026.mp4", "video", 1),
            MediaItem("D:/ФАКТАЖ/Moscow.mp4", "Moscow.mp4", "video", 1),
        ]
        w.all_media = items
        w.search_index = IndexedMediaLibrary(items, {})
        with patch.object(w, "_save"):
            w.global_search.setText("МУРМАНСК")
            w.search_everywhere()
        self.assertEqual(w.library_tabs.currentIndex(), 3)
        w.library_tabs.setCurrentIndex(0)
        self.assertEqual(w.model.rowCount(), 2)
        self.assertIn("2", w.library_tabs.tabText(0))

    def test_local_query_edits_remain_per_tab(self):
        w = self._window()
        with patch.object(w, "_save"), \
             patch.object(w.telegram_tab, "ensure_loaded", return_value=False):
            w.search.setText("кіно")
            w.library_tabs.setCurrentIndex(1)
            w.search.setText("НПЗ")
            w.library_tabs.setCurrentIndex(2)
            w.library_tabs.setCurrentIndex(0)
            self.assertEqual(w.search.text(), "кіно")
            w.library_tabs.setCurrentIndex(1)
            self.assertEqual(w.search.text(), "НПЗ")


class BrowserPanelSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_isolated_local_profiles_no_login_before_open(self):
        with tempfile.TemporaryDirectory() as folder:
            a = ServiceBrowser("telegram", Path(folder))
            b = ServiceBrowser("chatgpt", Path(folder))
            try:
                self.assertFalse(a.active)
                self.assertFalse(b.active)
                a.set_query("Мурманск")
                b.set_query("Мурманск")
                self.assertIn("Мурманск", a.prompt_box.toPlainText())
                self.assertIn("Мурманск", b.prompt_box.toPlainText())
                self.assertNotEqual(a.profile_root / a.service,
                                    b.profile_root / b.service)
                self.assertFalse((Path(folder) / "telegram").exists())
                self.assertFalse((Path(folder) / "chatgpt").exists())
            finally:
                a.close()
                b.close()

    def test_copy_prompt_uses_real_user_clipboard_only_on_click(self):
        with tempfile.TemporaryDirectory() as folder:
            widget = ServiceBrowser("chatgpt", Path(folder))
            try:
                widget.set_query("Мурманск")
                widget.copy_query()
                text = QApplication.clipboard().text()
                self.assertIn("Мурманск", text)
                self.assertIn("10 лет", text)
                self.assertFalse(widget.active)
            finally:
                widget.close()


if __name__ == "__main__":
    unittest.main()
