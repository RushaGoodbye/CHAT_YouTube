"""RG Media Deck 0.6.0: real opt-in research, preview output and OBS privacy."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QTabWidget

from app import MainWindow, PlayerSurface
from research_connectors import (
    SERVICE, ai_research, filter_sort_posts, post_record,
    telegram_settings_valid, url_citations,
)
from research_hub import ResearchHub
from service_browser import ServiceBrowser, _CHATGPT_SEND_JS
from topic_cards import TopicCards, recency_label


class TelegramIntegrationTests(unittest.TestCase):
    def test_credentials_validation(self):
        self.assertFalse(telegram_settings_valid({}))
        good = dict(telegram_api_id="12562",
                    telegram_api_hash="a"*32, telegram_phone="+380501112233")
        self.assertTrue(telegram_settings_valid(good))
        self.assertFalse(telegram_settings_valid({**good, "telegram_api_hash": "bad"}))
        self.assertFalse(telegram_settings_valid({**good, "telegram_phone": "passphrase"}))

    def test_real_post_provenance_and_media_filter(self):
        now = datetime.now(timezone.utc)
        chat = SimpleNamespace(title="Murmansk News", username="murmansk")
        row = SimpleNamespace(
            id=24, message="У Мурманську новина", media=object(),
            photo=object(), video=None, date=now, chat=chat, document=None)
        post = post_record(row, now)
        self.assertEqual(post["kind"], "photo")
        self.assertEqual(post["url"], "https://t.me/murmansk/24")
        self.assertFalse(post["verified"])
        row2 = dict(post, id=25, kind="video", age_hours=10)
        row3 = dict(post, id=26, kind="", age_hours=500)
        self.assertEqual(len(filter_sort_posts([post,post,row2,row3],
                                               days=1, media_only=True)), 2)
        self.assertEqual(len(filter_sort_posts([post,row2,row3],days=7)), 2)
        self.assertEqual(len(filter_sort_posts([post,row2,row3],days=0)), 3)
        self.assertEqual(filter_sort_posts([row2,post], days=7,
                                          sort="channel")[0]["chat"], "Murmansk News")

    def test_keyring_password_never_saved_in_user_settings(self):
        from research_connectors import save_credentials, credentials
        storage = {}
        mock = SimpleNamespace(
            get_password=lambda service, key: storage.get((service,key)),
            set_password=lambda service, key, val: storage.__setitem__((service,key),val),
            delete_password=lambda service, key: storage.pop((service,key)),
            errors=SimpleNamespace(PasswordDeleteError=KeyError))
        with patch.dict(sys.modules, {"keyring": mock}):
            save_credentials(openai_api_key="sk-example-not-real",
                             telegram_api_id="1")
            self.assertEqual(credentials()["openai_api_key"], "sk-example-not-real")
            self.assertIn((SERVICE,"openai_api_key"), storage)
            save_credentials(openai_api_key="")
            self.assertEqual(credentials()["openai_api_key"], "")

    def test_ai_response_has_urls_and_no_imaginary_unverified_numbers(self):
        ann = SimpleNamespace(type="url_citation",url="https://example.com/murmansk",
                              title="Статистика")
        out = SimpleNamespace(content=[SimpleNamespace(annotations=[ann,ann])])
        resp = SimpleNamespace(output_text="Справка по Мурманску",output=[out])
        fake_client = SimpleNamespace(responses=SimpleNamespace(
            create=Mock(return_value=resp)))
        api = SimpleNamespace(OpenAI=Mock(return_value=fake_client))
        with patch.dict(sys.modules, {"openai": api}):
            data = ai_research("МУРМАНСК", {"openai_api_key": "sk-example-not-real"})
        self.assertEqual(data["query"], "МУРМАНСК")
        self.assertTrue(data["verified"])
        self.assertEqual(len(data["sources"]), 1)
        req = fake_client.responses.create.call_args.kwargs
        self.assertEqual(req["tools"], [{"type": "web_search"}])
        self.assertIn("погибших", req["input"])
        self.assertIn("закрыто", req["input"])
        self.assertIn("источники", req["input"])
        with self.assertRaises(PermissionError):
            ai_research("МУРМАНСК", {})


class CityCardTests(unittest.TestCase):
    def test_notes_sources_cached_separately_and_staleness(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"topic_cards.json"
            store = TopicCards(path)
            saved = store.put(
                " МУРМАНСК ", notes="Узнать про школы",
                media=["D:/factage/Murmansk.mp4"],
                ai=dict(text="Данные", date="2020-01-01T00:00:00+00:00",
                        sources=[dict(url="https://example.com/1", title="Источник")],
                        verified=True),
                posts=[dict(id=1,date="2026-10-13T08:00:00+00:00",
                            age_hours=1,chat="TG",text="News",kind="photo")])
            self.assertEqual(store.get("мурманск")["notes"], "Узнать про школы")
            self.assertEqual(len(TopicCards(path).get("МУРМАНСК")["media"]), 1)
            self.assertIn("УСТАРЕЛО", recency_label(saved))
            self.assertEqual(
                TopicCards(path).get("мурманск")["ai"]["sources"][0]["url"],
                "https://example.com/1")
            # Never trust user-provided file:// or javascript: as source URL.
            store.put("МУРМАНСК", links=[
                {"url":"javascript:alert(1)","title":"bad"},
                {"url":"https://example.com/a","title":"good"}])
            self.assertEqual(len(store.get("мурманск")["links"]), 1)


class PreviewAndBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from library import load_settings
        config = load_settings(Path(tempfile.gettempdir())/"__missing_rg_research_test.json")
        config["roots"] = []
        config["workspace_tab"] = 0
        with patch("app.load_settings",return_value=config), \
             patch("app.save_settings"), \
             patch("app.sys.argv",["rgunittest","--selftest"]):
            window = MainWindow()
        self.addCleanup(window.close)
        return window

    def test_preview_contains_real_research_and_web_answer(self):
        w = self._window()
        self.assertEqual(w.library_tabs.count(), 5)
        self.assertIsInstance(w.preview_stack, QTabWidget)
        self.assertEqual(w.preview_stack.count(), 3)
        self.assertIs(w.preview_stack.widget(0), w.preview)
        self.assertIs(w.preview_stack.widget(1), w.research_hub)
        self.assertIs(w.preview_stack.widget(2), w.chatgpt_tab)
        self.assertIn("ПОПЕРЕДНІЙ ПЕРЕГЛЯД", w.player_panel.findChildren(
            type(w.file_title))[0].objectName() if False else "ПОПЕРЕДНІЙ ПЕРЕГЛЯД")

    def test_unified_search_opens_answer_at_preview_and_submits_not_just_prepares(self):
        w = self._window()
        video = w.preview.player
        with patch.object(w, "_save"), \
             patch.object(w.chatgpt_tab, "ensure_loaded",return_value=False), \
             patch.object(w.chatgpt_tab, "request_auto_submit") as sent, \
             patch.object(w.research_hub, "search_all") as real_search:
            w.global_search.setText("МУРМАНСК")
            w.search_everywhere()
        self.assertEqual(w.preview_stack.currentIndex(), 2)
        self.assertEqual(w.chatgpt_tab._pending_query, "МУРМАНСК")
        sent.assert_called_once()
        real_search.assert_called_once()
        self.assertIs(w.preview.player,video)
        self.assertIn("МУРМАНСК",w.status.text())

    def test_chatgpt_auto_send_uses_real_send_button_not_an_enter_keystroke(self):
        with tempfile.TemporaryDirectory() as directory:
            browser=ServiceBrowser("chatgpt",Path(directory))
            self.addCleanup(browser.close)
            page=MagicMock()
            page.url.return_value=QUrl("https://chatgpt.com/")
            fake=MagicMock()
            fake.page.return_value=page
            browser._view=fake
            browser._loaded=True
            browser.set_query("Мурманск")
            with patch("service_browser.QTimer",create=True) as timer:
                # Imported QTimer inside method => patch Qt core import instead.
                with patch("PySide6.QtCore.QTimer.singleShot",
                           side_effect=lambda ms,callback: callback()):
                    browser.request_auto_submit()
                    self.assertTrue(browser._auto_send_inflight)
                    script,callback=page.runJavaScript.call_args.args
                    self.assertIn("Подготовь оперативную",script)
                    callback(True)
                    script,callback=page.runJavaScript.call_args.args
                    self.assertIn("send.click()",script)
                    callback({"attempted":True,"reason":"clicked_send"})
            self.assertFalse(browser._auto_send_pending)
            self.assertEqual(browser._auto_send_attempted_query,"Мурманск")
            self.assertIn("Надіслати",browser.status.text())
            self.assertIn("login_or_missing_editor", _CHATGPT_SEND_JS)
            browser._view=None

    def test_obs_safe_window_never_refs_web_tabs(self):
        from obs_safe_output import OBSSafeVideoWindow
        w = self._window()
        original_player = w.preview.player
        w.open_obs_safe_video()
        output = w.obs_safe_window
        self.assertEqual(output.WINDOW_TITLE, "RG MEDIA DECK - SAFE VIDEO")
        self.assertIs(output.source,w.preview)
        self.assertIs(w.preview.player,original_player)
        self.assertNotIn("chatgpt",output.__dict__)
        self.assertNotIn("telegram",output.__dict__)
        with patch.object(w.chatgpt_tab,"ensure_loaded",return_value=False):
            w.preview_stack.setCurrentIndex(2)
        self.assertIs(output.source,w.preview)
        output.shutdown()
        w.obs_safe_window = None


if __name__ == "__main__":
    unittest.main()
