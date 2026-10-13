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
                self.assertNotIn(token, self.source)

    def test_only_two_library_tabs(self):
        self.assertIn("self.library_tabs.addTab('ФАКТАЖ')", self.source)
        self.assertIn("self.library_tabs.addTab('📰 НОВИНИ')", self.source)
        self.assertEqual(self.source.count("self.library_tabs.addTab("), 2)

    def test_one_media_preview_and_obs_safe(self):
        self.assertEqual(self.source.count("self.preview_stack.addTab("), 1)
        self.assertIn("OBSSafeVideoWindow(self.preview)", self.source)

    def test_no_service_dependencies(self):
        deps = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for package in ("telethon", "openai", "keyring"):
            self.assertNotIn(package, deps)

    def test_search_remains_local(self):
        functions = [n for n in ast.walk(self.tree) if
                     isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        search = next(n for n in functions if n.name == "search_everywhere")
        code = ast.get_source_segment(self.source, search)
        self.assertIn("self.search_index.filter(", code)
        self.assertIn("self.apply_filter()", code)
        self.assertNotIn("request_auto_submit", code)
        self.assertNotIn("search_all(", code)


if __name__ == "__main__":
    unittest.main()
