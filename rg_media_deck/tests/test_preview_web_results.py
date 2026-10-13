"""0.5.2: Results are on the RIGHT; user-requested ChatGPT auto-send."""
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from service_browser import _CHATGPT_PREPARE_JS, ServiceBrowser
from app import MainWindow
from library import load_settings
from pathlib import Path
import tempfile


class RightSideResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_right_preview_hosts_chatgpt_and_telegram_not_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=load_settings(Path(tmp)/"missing.json")
            config["roots"]=[]
            with patch("app.load_settings",return_value=config), \
                 patch("app.save_settings"), \
                 patch("app.sys.argv",["test","--selftest"]):
                window=MainWindow()
            try:
                self.assertIs(window.preview_stack.widget(0),window.preview)
                self.assertIs(window.preview_stack.widget(1),window.telegram_tab)
                self.assertIs(window.preview_stack.widget(2),window.chatgpt_tab)
                original=window.preview.player
                with patch.object(window.telegram_tab,"ensure_loaded",return_value=True), \
                     patch.object(window.chatgpt_tab,"ensure_loaded",return_value=True), \
                     patch.object(window,"_save"):
                    window.library_tabs.setCurrentIndex(2)
                    self.assertEqual(window.preview_stack.currentIndex(),1)
                    self.assertEqual(window.left_stack.currentIndex(),1)
                    window.library_tabs.setCurrentIndex(3)
                    self.assertEqual(window.preview_stack.currentIndex(),2)
                    window.library_tabs.setCurrentIndex(0)
                    self.assertEqual(window.preview_stack.currentIndex(),0)
                    self.assertIs(window.preview.player,original)
            finally:
                window.close()

    def test_chatgpt_script_clicks_actual_send_button_not_only_fills(self):
        self.assertIn('send.click()',_CHATGPT_PREPARE_JS)
        self.assertIn('SUBMITTED_CLICK',_CHATGPT_PREPARE_JS)
        self.assertIn("SEND_BUTTON_NOT_READY",_CHATGPT_PREPARE_JS)
        self.assertIn("LOGIN_REQUIRED",_CHATGPT_PREPARE_JS)

    def test_submit_state_never_claims_success_if_dom_not_ready(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            browser=ServiceBrowser("chatgpt",Path(folder))
            try:
                browser._on_search_attempt("SEND_BUTTON_NOT_READY")
                self.assertFalse(browser._search_result)
                self.assertIn("Не підтверджено",browser.status.text())
                browser._on_search_attempt("SUBMITTED_CLICK")
                self.assertTrue(browser._search_result)
            finally:
                browser.close()


if __name__=="__main__":
    unittest.main()
