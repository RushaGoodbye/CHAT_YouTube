import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"rg_remote_control"/"auto_edit_features"/"guest_reference_903_evidence_v1.py"
spec=importlib.util.spec_from_file_location("guest_reference_903_evidence",SCRIPT)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class FakeImage:
    shape=(1280,591,3)
    def __getitem__(self, region):
        return self

def fake_face_finder(image,score_threshold=.50,min_face_px=24):
    return [
        {"bbox":[430,175,80,100],"center_x":470,"area":8000,"score":.90},
        {"bbox":[20,100,55,66],"center_x":48,"area":3630,"score":.77},
    ]

class ReferenceEvidenceTests(unittest.TestCase):
    def test_all_crop_modes_preserve_right_guest_candidate(self):
        found=m.detections(FakeImage(),fake_face_finder)
        self.assertEqual([x["roi"] for x in found],["UPPER_48","UPPER_70","FULL"])
        self.assertTrue(all(x["right_guest_candidates"]==1 for x in found))

    def test_source_sampling_never_changes_files(self):
        def frames(*args,**kwargs):
            for sec in [3600.,3603.,3606.]:
                yield sec,None
        def state(frame, refs, **kwargs):
            return ("CURRENT",{},.70,1,None)
        result=m.visual_window("F:/VIDEO.mkv","REF",("EARLY",3593,3730,.33),frames,state)
        self.assertEqual(result["current_hits"],3)
        self.assertEqual(result["current_times_first"],[3600.,3603.,3606.])

    def test_unknown_frames_are_not_approved(self):
        def frames(*args,**kwargs):
            yield 4000.,None
        def state(*args,**kwargs):
            return ("PLACEHOLDER",{},0.,0,None)
        result=m.visual_window("source","guest",("ANCHOR",3875,4030,.33),frames,state)
        self.assertEqual(result["placeholder_hits"],1)
        self.assertEqual(result["current_hits"],0)

    def test_no_media_modification_or_auto_release(self):
        src=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"media_writes":0',src)
        self.assertIn('"xml_writes":0',src)
        self.assertIn('"auto_approve_guest":False',src)
        for forbidden in ("unlink(","write_text(","write_bytes(","cv2.imwrite","os.replace("):
            self.assertNotIn(forbidden,src)

if __name__=="__main__":
    unittest.main()
