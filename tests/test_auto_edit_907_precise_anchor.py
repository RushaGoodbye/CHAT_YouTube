import importlib.util
from pathlib import Path
import unittest
SCRIPT=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"precise_guest_anchor_907_v1.py"
spec=importlib.util.spec_from_file_location("precise_907",SCRIPT)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class Tests(unittest.TestCase):
    def test_accepts_only_visual_and_guest(self):
        frames=((4500+i,None) for i in range(4))
        def current(_):return "CURRENT",{},.75,1,None
        r=mod.validate({"time":4571,"score":.51},4550,4620,frames,current)
        self.assertTrue(r["verified"])
    def test_rejects_misplaced_frame(self):
        r=mod.validate({"time":4938.5,"score":.99},4550,4620,[],lambda f:None)
        self.assertFalse(r["verified"])
    def test_rejects_other_guest(self):
        r=mod.validate({"time":4571,"score":.9},4550,4620,
          [(4555,None),(4558,None)],lambda _:("OTHER_FACE",{},.92,1,None))
        self.assertFalse(r["verified"])
    def test_never_writes(self):
        s=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"automatic_clock_override":False',s)
        self.assertIn('"xml_writes":0',s)
        self.assertNotIn("unlink(",s)
if __name__=="__main__":unittest.main()
