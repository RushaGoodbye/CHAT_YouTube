import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"replay_9032_proven_guest_v1.py"
spec=importlib.util.spec_from_file_location("replay_9032",SCRIPT)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Targeted903ReplayTests(unittest.TestCase):
    def test_only_9032_anchor_and_interval_changes(self):
        def original(parent,match,previous_match=None,next_match=None):
            return {"identity_context":{"current_anchor_sec":3953.5,
                        "legacy_interval":{"start":3893,"end":4013},
                        "capture_interval":{"start":2993.5,"end":6249}},
                    "selected_ranges":[{"start":2993.5,"end":6249}],
                    "selected_total_sec":3255.5}
        chosen=m.reanchor(original,{},{"screenshot":"903-2.jpg"})
        self.assertEqual(chosen["identity_context"]["current_anchor_sec"],3608.65)
        self.assertEqual(chosen["selected_ranges"][0]["start"],3450.)
        self.assertEqual(chosen["selected_ranges"][0]["end"],3820.)
        untouched=m.reanchor(original,{},{"screenshot":"903-5.jpg"})
        self.assertEqual(untouched["identity_context"]["current_anchor_sec"],3953.5)

    def test_proof_refuses_changed_timestamp(self):
        def drifted(*args,**kwargs):
            return {"identity_context":{"current_anchor_sec":5111.}}
        with self.assertRaisesRegex(RuntimeError,"clock evidence changed"):
            m.reanchor(drifted,{},{"screenshot":"903-2.jpg"})

    def test_complete_manifest_with_9032_9035_holds(self):
        with tempfile.TemporaryDirectory() as d:
            outputs=[]
            for i in [1,3,4,6]:
                p=Path(d)/f"903_{i}.xml"
                p.write_text(f"xml {i}",encoding="utf-8")
                outputs.append({"index":i,"xml":str(p)})
            doc={"stream":"903","status":"PARTIAL_REVIEW","dialogue_count":6,
                 "outputs":outputs,"review_holds":[{"index":2},{"index":5}]}
            sha=m.manifest_gate(doc)
            self.assertEqual(sorted(sha),[1,3,4,6])
            doc["status"]="DIALOGUES_COMPLETE"
            with self.assertRaisesRegex(RuntimeError,"original manifest changed"):
                m.manifest_gate(doc)

    def test_no_unrelated_media_deletion(self):
        s=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('os.environ["RG_ONLY_DIALOGUE_INDEXES"]="2"',s)
        self.assertIn('os.environ["RG_FORCE_SELECTED_DIALOGUES"]="1"',s)
        self.assertIn('shutil.copy2(old,ROOT)',s)
        self.assertNotIn("unlink(",s)
        self.assertNotIn("Stop-Process",s)

if __name__=="__main__":
    unittest.main()
