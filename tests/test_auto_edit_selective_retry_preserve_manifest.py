import ast
import importlib.util
from pathlib import Path
import unittest

SOURCE=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"selective_retry_preserve_manifest_v1.py"
spec=importlib.util.spec_from_file_location("selective_retry_preserve",SOURCE)
fix=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)

def source_fixture():
    return ("def main():\n"
            + fix.ANCHOR_A + "\n"
            + "        'dialogue_count':total,\n"
            + "    }\n"
            + "    for i in range(total):\n"
            + fix.ANCHOR_B + "\n"
            + "        can_resume=True\n"
            + fix.ANCHOR_C + "\n"
            + "            pass\n"
            + "        try:\n"
            + "            pass\n"
            + fix.ANCHOR_D + "\n"
            + fix.ANCHOR_E + "\n"
            + "    return manifest\n")

class SelectiveRetryPreserveManifestTests(unittest.TestCase):
    def test_903_two_holds_preserve_all_four_ready_xmls(self):
        outputs=[{"index":i,"xml":f"RG_EDITED_903_{i}.xml"}
                 for i in (1,3,4,6)]
        holds=[{"index":i,"status":"HOLD_FOR_REVIEW"} for i in (2,5)]
        ready,held=fix.planned_preservation(outputs,holds,{2,5},6)
        self.assertEqual([x["index"] for x in ready],[1,3,4,6])
        self.assertEqual(held,[])
        self.assertEqual(len(outputs),4)

    def test_selective_retry_only_901_4_5_6_preserves_1_2_3(self):
        outputs=[{"index":i,"xml":f"901_{i}.xml"} for i in range(1,7)]
        ready,held=fix.planned_preservation(outputs,[],{4,5,6},6)
        self.assertEqual([x["index"] for x in ready],[1,2,3])
        self.assertFalse(held)

    def test_invalid_duplicate_manifest_rejected(self):
        bad=[{"index":1},{"index":1},{"index":3}]
        with self.assertRaises(RuntimeError):
            fix.planned_preservation(bad,[{"index":2}],{2},3)

    def test_incomplete_original_manifest_rejected(self):
        with self.assertRaises(RuntimeError):
            fix.planned_preservation([{"index":1},{"index":2}],[],{2},3)

    def test_patch_valid_python_and_idempotence(self):
        raw=source_fixture()
        ast.parse(raw)
        out,status=fix.patch_source(raw)
        self.assertEqual(status,"PATCH_READY")
        ast.parse(out)
        self.assertIn("RG_ONLY_DIALOGUE_INDEXES",out)
        self.assertIn("RG_FORCE_SELECTED_DIALOGUES",out)
        self.assertIn("RGSELECTIVE|ROLLBACK|MANIFEST_RESTORED",out)
        again,status=fix.patch_source(out)
        self.assertEqual(status,"ALREADY_PATCHED")
        self.assertEqual(again,out)

    def test_unrecognized_source_refused(self):
        with self.assertRaisesRegex(RuntimeError,"source anchor"):
            fix.patch_source("def main():\n    return None\n")

    def test_patch_installer_never_runs_stream(self):
        script=SOURCE.read_text(encoding="utf-8")
        self.assertIn('"dialogue_processing_started":False',script)
        self.assertIn('"media_writes":0',script)
        self.assertIn('"xml_writes":0',script)
        self.assertNotIn("subprocess.run",script)

if __name__=="__main__":
    unittest.main()
