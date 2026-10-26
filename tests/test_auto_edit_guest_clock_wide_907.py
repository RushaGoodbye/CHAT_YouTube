import importlib.util, unittest
from pathlib import Path
SRC=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"guest_clock_wide_907_v1.py"
spec=importlib.util.spec_from_file_location("guest_clock_wide_907",SRC)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class ScanContracts(unittest.TestCase):
    def test_capped_candidate_windows(self):
        windows=mod.windows_from_clock([6000],12000,lambda secs,h:secs-(h-20)*3600)
        self.assertEqual(len(windows),2)
        self.assertEqual(windows[0]["clock_candidate_sec"],6000)
        self.assertEqual(windows[1]["clock_candidate_sec"],2400)
        self.assertTrue(all(w["end"]-w["start"]<=1440. for w in windows))

    def test_current_guest_recorded_without_automatic_approval(self):
        seq=iter([(100.,None),(105.,None),(110.,None)])
        def classifier(img,ref,**kw):
            state="CURRENT" if classifier.count!=1 else "OTHER_FACE"
            classifier.count+=1
            return state,{},.72,1,None
        classifier.count=0
        row=mod.summarize_frames(seq,{1:"face"},classifier)
        self.assertEqual(row["guests"]["1"]["current"],2)
        self.assertEqual(row["guests"]["1"]["other"],1)
        text=SRC.read_text(encoding="utf-8")
        self.assertIn('"auto_release":False',text)
        self.assertIn('"xml_writes":0',text)

if __name__=="__main__":unittest.main()
