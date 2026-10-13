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

    def test_telegram_duplicate_articles_across_channels_are_collapsed(self):
        now = datetime.now(timezone.utc).isoformat()
        story = "В Мурманске закрыли учреждение, официальный список и документы опубликованы сегодня."
        base = dict(date=now, kind="video", text=story,
                    age_hours=1.0)
        posts = [
            dict(base, id=1, chat="Новости 1", url="https://t.me/news1/1"),
            dict(base, id=2, chat="Новости 2", url="https://t.me/news2/2"),
            dict(base, id=3, chat="Новости 2", text="Коротко"),
        ]
        result = filter_sort_posts(posts, days=1)
        self.assertEqual(len(result), 2)
        self.assertEqual(len([p for p in result if p["text"] == story]), 1)

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


class LocalPreviewAndOBSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_local_preview_only_and_obs_safe_output(self):
        from library import load_settings
        config = load_settings(Path(tempfile.gettempdir()) / "__missing_local_preview.json")
        config["roots"] = []
        config["workspace_tab"] = 0
        with patch("app.load_settings", return_value=config), patch("app.save_settings"), patch("app.sys.argv", ["test", "--selftest"]):
            w = MainWindow()
        try:
            self.assertEqual(w.library_tabs.count(), 2)
            self.assertEqual(w.preview_stack.count(), 1)
            self.assertIs(w.preview_stack.widget(0), w.preview)
            original = w.preview.player
            w.open_obs_safe_video()
            self.assertEqual(w.obs_safe_window.WINDOW_TITLE, "RG MEDIA DECK - SAFE VIDEO")
            self.assertIs(w.obs_safe_window.source, w.preview)
            self.assertIs(w.preview.player, original)
        finally:
            w.close()


if __name__ == "__main__":
    unittest.main()
