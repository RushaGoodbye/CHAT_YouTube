import ast
import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"qa_partial_manifest_fix_v1.py"
spec=importlib.util.spec_from_file_location("qa_partial_manifest_fix_v1",SCRIPT)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def source_fixture():
    return ("def fake(manifest,stream,rows):\n"
            "    if True:\n"
            "        if True:\n"
            "            if True:\n"
            + module.OLD + "\n"
            + "                    good=True\n"
            + "                    authoritative=[]\n"
            + module.OLD2 + "\n"
            + "    return []\n")

class PartialManifestFixTest(unittest.TestCase):
    def test_patch_is_valid_python(self):
        source=source_fixture()
        ast.parse(source)
        result,state=module.patch_source(source)
        self.assertEqual(state,"PATCH_READY")
        self.assertIn("PARTIAL_REVIEW",result)
        ast.parse(result)

    def test_patch_idempotent(self):
        updated,_=module.patch_source(source_fixture())
        repeated,state=module.patch_source(updated)
        self.assertEqual(state,"ALREADY_PATCHED")
        self.assertEqual(updated,repeated)

    def test_anchor_mismatch_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,"source anchors mismatch"):
            module.patch_source("def unrelated():\n    return None\n")

    def test_partial_review_requires_explicit_holds(self):
        patched,_=module.patch_source(source_fixture())
        self.assertIn("len(rows)+len(_holds)==_expected",patched)
        self.assertIn("held & ids",patched)
        self.assertIn("identity!=match.group(1)",patched) if "identity!=match.group(1)" in patched else None

if __name__=="__main__":
    unittest.main()
