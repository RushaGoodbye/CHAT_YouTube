import importlib.util
import unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"visual_proof_907_v1.py"
spec=importlib.util.spec_from_file_location("visual_proof_907_v1",SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class ProbeTests(unittest.TestCase):
    def test_counts_verified_guest_only(self):
        def frames():
            for k in range(4): yield 4000.+k,None
        def classifier(frame,ref,**kw):
            classifier.calls+=1
            if classifier.calls==2:return ("OTHER_FACE",{},.92,1,None)
            return ("CURRENT",{},.72,1,None)
        classifier.calls=0
        out=mod.compact(frames(),"guest",classifier)
        self.assertEqual(out["frames_checked"],4)
        self.assertEqual(out["states"]["CURRENT"],3)
        self.assertEqual(out["states"]["OTHER_FACE"],1)

    def test_two_competing_anchors_reported_not_approved(self):
        self.assertIn("clock_grid",mod.WINDOWS)
        self.assertIn("local_visual",mod.WINDOWS)
        text=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"identity_ambiguous"',text)
        self.assertIn('"xml_writes":0',text)
        self.assertNotIn("os.replace(",text)
        self.assertNotIn("cv2.imwrite(",text)

if __name__=="__main__":
    unittest.main()
