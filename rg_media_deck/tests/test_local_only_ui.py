"""Ensure local-only UI cannot silently regain network tabs or searches."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LocalOnlyUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_no_browser_widgets_or_research_hub(self):
        forbidden = ("ServiceBrowser", "ResearchHub",
                     "telegram_tab", "chatgpt_tab", "research_hub",
                     "QWebEngineView", "webengine-selftest")
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn("self." + token + " =", self.source)
                self.assertNotIn("from " + token + " import", self.source)

    def test_only_two_library_tabs(self):
        self.assertIn("self.library_tabs.addTab('ФАКТАЖ')", self.source)
        self.assertIn("self.library_tabs.addTab('📰 НОВИНИ')", self.source)
        self.assertEqual(self.source.count("self.library_tabs.addTab("), 2)

    def test_single_media_preview_without_separate_output(self):
        self.assertEqual(self.source.count("self.preview_stack.addTab("), 1)
        self.assertNotIn("OBSSafeVideoWindow(self.preview)", self.source)

    def test_no_service_dependencies(self):
        deps = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for package in ("telethon", "openai", "keyring"):
            self.assertNotIn(package, deps)

    def test_only_in_panel_search_and_no_crossed_out_controls(self):
        self.assertIn("self.search = QLineEdit()", self.source)
        for symbol in ("global_search = QLineEdit", "fast_row = QHBoxLayout",
                       "show_staged_preview", "open_play_history",
                       "suggest_search", "assign_quick_slot"):
            self.assertNotIn(symbol, self.source)


if __name__ == "__main__":
    unittest.main()
