import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"clock_guest_shadow_907_v1.py"
spec=importlib.util.spec_from_file_location("clock_907_shadow",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Clock907Tests(unittest.TestCase):
    def test_actual_face_evidence_required(self):
        yes={"samples":22,"current_hits":16,"best_score":.75}
        no={"samples":22,"current_hits":0,"best_score":.20}
        self.assertEqual(m.verdict(no,yes),
            "LOCAL_GUEST_EVIDENCE_STRONG_NOT_AUTOMATICALLY_APPROVED")
        self.assertEqual(m.verdict(yes,no),
            "GRID_GUEST_EVIDENCE_STRONG_NOT_AUTOMATICALLY_APPROVED")
        self.assertEqual(m.verdict(no,no),
            "GUEST_CLOCK_CORRECTION_NOT_PROVEN")
        self.assertEqual(m.verdict(yes,yes),
            "BOTH_GUEST_CANDIDATES_AMBIGUOUS")

    def test_sampling_does_not_approve_without_face(self):
        def frames(*args,**kwargs):
            for i in range(10):yield 4814.8+i,None
        def identity(*args,**kwargs):
            return ("PLACEHOLDER",{},.0,0,None)
        row=m.sample("video","ref",4814.8,frames,identity)
        self.assertEqual(row["current_hits"],0)
        self.assertEqual(row["samples"],10)

    def test_read_only_contract(self):
        s=p.read_text(encoding="utf-8")
        self.assertIn('"auto_reanchor":False',s)
        self.assertIn('"xml_writes":0',s)
        self.assertNotIn("write_text(",s)
        self.assertNotIn("os.replace(",s)
        self.assertNotIn("unlink(",s)

if __name__=="__main__":
    unittest.main()
