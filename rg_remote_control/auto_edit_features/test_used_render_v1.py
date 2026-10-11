from __future__ import annotations
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("rg_used_dialogues_under_test",HERE/"rg_used_dialogues.py")
registry=importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)

class UsedDialoguesTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        registry.DATA_DIR=Path(self.t.name)
        registry.DB=registry.DATA_DIR/"used_v2.json"
        registry.LEGACY=registry.DATA_DIR/"legacy.json"
        self.dialogue=r"D:\videos\891-2.mp4"
        self.dialogue2=r"D:\videos\890-6.mp4"
        self.output=registry.DATA_DIR/"final.mp4"
        self.output.write_bytes(b"x"*4096)

    def test_manual_and_reversal(self):
        self.assertFalse(registry.status(self.dialogue)["used"])
        registry.manual_mark([self.dialogue,self.dialogue2],True)
        self.assertTrue(registry.status(self.dialogue)["used"])
        self.assertTrue(registry.status(self.dialogue2)["used"])
        registry.manual_mark([self.dialogue],False)
        self.assertFalse(registry.status(self.dialogue)["used"])
        self.assertTrue(registry.status(self.dialogue2)["used"])

    def test_success_history_deduplicated_and_reversible(self):
        self.assertEqual(registry.record_success([self.dialogue],self.output,"JOB1"),1)
        self.assertEqual(registry.record_success([self.dialogue],self.output,"JOB1"),0)
        self.assertEqual(registry.status(self.dialogue)["count"],1)
        registry.manual_mark([self.dialogue],False)
        self.assertFalse(registry.status(self.dialogue)["used"])
        self.assertEqual(registry.record_success([self.dialogue],self.output,"JOB2"),1)
        state=registry.status(self.dialogue)
        self.assertTrue(state["used"])
        self.assertEqual(state["count"],2)
        self.assertEqual(state["last_output"],str(self.output))

    def test_no_mark_on_missing_output(self):
        with self.assertRaises(RuntimeError):
            registry.record_success([self.dialogue],registry.DATA_DIR/"missing.mp4","BAD")
        self.assertFalse(registry.status(self.dialogue)["used"])

    def test_legacy_read_without_rename(self):
        registry.LEGACY.write_text(json.dumps({"used":[self.dialogue]}),encoding="utf-8")
        self.assertTrue(registry.status(self.dialogue)["used"])
        registry.manual_mark([self.dialogue],False)
        self.assertFalse(registry.status(self.dialogue)["used"])

    def test_corrupt_v2_fails_closed(self):
        registry.DB.write_text("{ broken",encoding="utf-8")
        with self.assertRaises(RuntimeError):
            registry.manual_mark([self.dialogue],True)

if __name__=="__main__":
    unittest.main(verbosity=2)
