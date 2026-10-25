import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

p=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"partial_ui_status_audit_v1.py"
spec=importlib.util.spec_from_file_location("partial_ui_status",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class PartialUIStatusAuditTests(unittest.TestCase):
    def test_bounded_snippet_and_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"dummy.py").write_text("x=1\ndef _batch_finished():\n    return 4\n",encoding="utf-8")
            with patch.object(mod,"APP",root):
                result=mod.extract("dummy.py",("def _batch_finished",))
        self.assertEqual(result["patterns"]["def _batch_finished"]["hits"],1)
        self.assertIn("return 4",result["patterns"]["def _batch_finished"]["excerpts"][0]["text"])

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(mod,"APP",Path(d)):
                self.assertTrue(mod.extract("missing.py",("x",))["missing"])

    def test_no_write_functions(self):
        s=p.read_text(encoding="utf-8")
        self.assertNotIn("write_text(",s)
        self.assertNotIn("subprocess",s)
        self.assertNotIn("unlink(",s)

if __name__=="__main__":
    unittest.main()
