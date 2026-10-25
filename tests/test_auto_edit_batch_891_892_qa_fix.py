import ast
import importlib.util
from pathlib import Path
import unittest

MODULE=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"batch_891_892_qa_fix_v1.py"
spec=importlib.util.spec_from_file_location("batch_891_892_qa_fix",MODULE)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class BatchManifestQARegression(unittest.TestCase):
    def test_helper_parses(self):
        tree=ast.parse(mod.INVENTORY_METHOD)
        self.assertIn("_rg_current_manifest_inventory",mod.INVENTORY_METHOD)
        self.assertIn("DIALOGUES_COMPLETE",mod.INVENTORY_METHOD)
        self.assertIn("legacy_single",mod.INVENTORY_METHOD)
        self.assertTrue(tree.body)

    def test_expected_real_891_892_screenshots(self):
        self.assertEqual(mod.TARGETS["891"],{"6"})
        self.assertEqual(mod.TARGETS["892"],{"3","5","6"})

    def test_source_anchors_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError,"source anchor"):
            mod.patch_source("def irrelevant(): return None")

    def test_no_auto_accept_partial_or_unsanctioned_media_changes(self):
        source=MODULE.read_text(encoding="utf-8")
        self.assertIn("PARTIAL_REVIEW",source)
        self.assertIn('"media_writes":0',source)
        self.assertIn('"xml_writes":0',source)
        self.assertIn("RG_POSTRUN_QA_ONLY",source)
        self.assertIn("shutil.copy2(backup/MODULE,src_path)",source)

if __name__=="__main__":
    unittest.main()
