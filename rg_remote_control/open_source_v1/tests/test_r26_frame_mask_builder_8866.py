#!/usr/bin/env python3
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r26_frame_mask_builder_8866 import build
from r26_presence_gate_8866 import evaluate, SCHEMA

def manifest():
    e=[]
    for f in range(8):
        e.append({"frame":f,"participant":"guest","object":"bottle",
                  "presence":"present" if f in (1,2,5) else "absent",
                  "bbox":[40+f,10,56+f,34] if f in (1,2,5) else None,
                  "semantic_verified":True})
    return {"schema":SCHEMA,"width":100,"height":60,"frame_count":8,
            "cut_frames":[4],"required_pairs":[{"participant":"guest","object":"bottle"}],
            "evidence":e, "masks":[]}

class BuilderTests(unittest.TestCase):
    def test_only_verified_frames(self):
        r=build(manifest())
        self.assertEqual([(m["start"],m["end"]) for m in r["masks"]],[(1,2),(2,3),(5,6)])
        self.assertTrue(evaluate(r)["structural_candidate_pass"])
        self.assertFalse(evaluate(r)["release_ready"])
    def test_no_extension_across_absence_or_cut(self):
        r=build(manifest())
        self.assertFalse(any(m["start"]==4 for m in r["masks"]))
        self.assertFalse(any(m["start"]<4<m["end"] for m in r["masks"]))
    def test_unknown_does_not_invent_mask(self):
        d=manifest()
        d["evidence"][1]["semantic_verified"]=False
        r=build(d)
        self.assertEqual(len(r["masks"]),2)
        self.assertFalse(evaluate(r)["structural_candidate_pass"])
    def test_absent_prohibits_box(self):
        d=manifest();d["evidence"][0]["bbox"]=[1,1,3,3]
        with self.assertRaises(ValueError):build(d)
    def test_reject_in_place_replacement(self):
        d=manifest();d["masks"]=[{"start":0}]
        with self.assertRaises(ValueError):build(d)
    def test_duplicate_frame_rejected(self):
        d=manifest();d["evidence"].append(copy.deepcopy(d["evidence"][1]))
        with self.assertRaises(ValueError):build(d)
    def test_unverified_present_must_not_authorize_release(self):
        d=manifest();d["evidence"][2]["semantic_verified"]=False
        r=build(d)
        self.assertFalse(r["candidate_release_approved"])
        self.assertFalse(evaluate(r)["structural_candidate_pass"])
    def test_immutable_source_manifest(self):
        d=manifest();before=copy.deepcopy(d);build(d);self.assertEqual(d,before)
if __name__=="__main__":unittest.main()
