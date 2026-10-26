import importlib.util
import tempfile
import unittest
from pathlib import Path

SRC=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"studio_live_gui_smoke_v1.py"
spec=importlib.util.spec_from_file_location("studio_live_gui_smoke_v1",SRC)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class StudioGuiReadOnlyTests(unittest.TestCase):
    def test_title_match_restricts_to_studio(self):
        self.assertTrue(mod.title_matches("RG AUTO EDIT STUDIO"))
        self.assertTrue(mod.title_matches("Auto Edit Studio - 903"))
        self.assertFalse(mod.title_matches("RG YouTube Control"))
        self.assertFalse(mod.title_matches(""))

    def test_missing_gui_is_not_marked_pass(self):
        with tempfile.TemporaryDirectory() as d:
            original=mod.visible_windows
            try:
                mod.visible_windows=lambda:[]
                result=mod.report(Path(d))
                self.assertFalse(result["tested_real_gui"])
                self.assertEqual(result["gui_result"],"NOT_TESTED_NO_VISIBLE_WINDOW")
                self.assertTrue(all(x=="MISSING" for x in result["required_source_syntax"].values()))
            finally:
                mod.visible_windows=original

    def test_win32_probe_does_not_mutate_studio(self):
        txt=SRC.read_text(encoding="utf-8")
        self.assertIn("SendMessageTimeoutW",txt)
        self.assertIn('"studio_restarted":False',txt)
        self.assertIn('"queue_writes":0',txt)
        self.assertNotIn("TerminateProcess",txt)
        self.assertNotIn("Stop-Process",txt)
        self.assertNotIn("os.replace(",txt)

if __name__=="__main__":
    unittest.main()
