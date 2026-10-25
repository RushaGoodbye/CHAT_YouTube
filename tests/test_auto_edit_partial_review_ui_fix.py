import ast
import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"partial_review_ui_fix_v1.py"
spec=importlib.util.spec_from_file_location("partial_review_ui_fix_v1",SCRIPT)
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

def fixture():
    return ("class Dummy:\n"
            "    def recheck(self):\n"
            "        if True:\n" + p.OLD_QA + "\n"
            "    def postrun(self):\n" + p.OLD_POST + "\n"
            "            pass\n"
            "    def batch(self):\n"
            "        if True:\n" + p.OLD_BATCH + "\n")

class PartialReviewUIFixTests(unittest.TestCase):
    def test_dry_run_patch_valid_python(self):
        text=fixture()
        ast.parse(text)
        result,status=p.patch_source(text)
        self.assertEqual(status,"PATCH_READY")
        ast.parse(result)
        self.assertIn("PARTIAL_REVIEW",result)
        self.assertIn("IDENTITY_REVIEW",result)
        self.assertIn("RG_PARTIAL_REVIEW_UI",result)

    def test_idempotence_and_mismatch_fail_closed(self):
        modified,_=p.patch_source(fixture())
        reread,status=p.patch_source(modified)
        self.assertEqual(status,"ALREADY_PATCHED")
        self.assertEqual(reread,modified)
        with self.assertRaisesRegex(RuntimeError,"Source anchor"):
            p.patch_source("class A: pass\n")

    def test_only_verified_primary_xml_and_review_holds(self):
        changed,_=p.patch_source(fixture())
        self.assertIn("(_done|_held)==set(range(1,_total+1))",changed)
        self.assertIn("and all(_checks.get(name,False) for name in _required)",changed)
        self.assertIn("not previous_ok",changed)
        self.assertIn("self._rg_partial_review_pending=False",changed)
        self.assertIn("HOLD_FOR_REVIEW",changed)

    def test_no_video_xml_and_report_mutation(self):
        code=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"xml_writes":0',code)
        self.assertIn('"media_writes":0',code)
        self.assertIn('"reports_unchanged":True',code)

if __name__=="__main__":
    unittest.main()
