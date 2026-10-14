#!/usr/bin/env python3
"""R27 motion, cut, occlusion and fail-closed regression on synthetic VIDEO FRAMES."""
from __future__ import annotations
import copy
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r27_anchor_tracker_8866 import SCHEMA, track, validate


def clip(n=22, visible_until=None, cut_at=None, empty=False):
    rng = np.random.default_rng(3421)
    background = rng.integers(28, 51, (90, 200, 3), dtype=np.uint8)
    patch = np.zeros((24, 16, 3), dtype=np.uint8)
    # Distinctive local appearance, consistent across frames.
    patch[:, :, :] = (20, 175, 210)
    cv2.line(patch, (0, 2), (15, 20), (245, 30, 35), 3)
    cv2.line(patch, (2, 22), (13, 2), (20, 240, 20), 2)
    cv2.rectangle(patch, (3, 3), (13, 20), (255, 70, 90), 1)
    frames=[]
    for f in range(n):
        image=background.copy()
        if cut_at is not None and f >= cut_at:
            image[:] = (185, 160, 200)
        if not empty and (visible_until is None or f < visible_until):
            x=119 + f*2
            image[28:52, x:x+16] = patch
        frames.append(image)
    return frames


def config(anchor=3, bbox=None, max_track=15, cuts=None):
    return {
        "schema":SCHEMA, "frame_count":22, "width":200, "height":90,
        "participant_rois":{"host":[0,0,100,90], "guest":[100,0,200,90]},
        "cut_frames": cuts if cuts is not None else [],
        "max_track_frames":max_track, "min_match_score":0.94,
        "anchors":[{
            "frame":anchor, "participant":"guest", "object":"bottle",
            "bbox":bbox if bbox is not None else [119+anchor*2,28,135+anchor*2,52],
            "semantic_verified":True, "provenance":"independent_visual_review",
            "track_id":"bottle-right-1"
        }]
    }


class R27TrackerTests(unittest.TestCase):
    def test_real_pixels_motion_forward_backward(self):
        frames = clip()
        r = track(frames.__getitem__, config())
        observed = {a["frame"]: a for a in r["candidates"]}
        self.assertTrue(all(f in observed for f in range(0, 19)))
        for f in range(19):
            # Local tracking must follow moving pixels, not just the seed's rectangle.
            got = observed[f]["source_object_bbox"]
            self.assertLess(abs(got[0] - (119 + 2*f)), 1)
            self.assertFalse(observed[f]["status"] == "PRODUCTION")
        self.assertFalse(r["release_ready"])
        self.assertFalse(r["pixel_blur_qa_verified"])

    def test_enforced_cut_never_tracks_beyond(self):
        frames=clip(cut_at=10)
        r=track(frames.__getitem__,config(anchor=8,cuts=[10],max_track=15))
        self.assertTrue(r["candidates"])
        self.assertLess(max(x["frame"] for x in r["candidates"]),10)
        self.assertTrue(any(x["reason"]=="SCENE_CUT_OR_CLIP_BOUNDARY"
                            for x in r["abstentions"]))

    def test_unmarked_hard_cut_stops(self):
        frames=clip(cut_at=10)
        r=track(frames.__getitem__,config(anchor=8,cuts=[],max_track=15))
        self.assertLess(max(x["frame"] for x in r["candidates"]), 10)
        self.assertTrue(any(x["reason"] in ("VISUAL_SCENE_CHANGE",
                                            "APPEARANCE_OR_MOTION_AMBIGUOUS")
                            for x in r["abstentions"]))

    def test_object_occlusion_abstains(self):
        frames=clip(visible_until=11)
        r=track(frames.__getitem__,config(anchor=7,max_track=12))
        self.assertLess(max(x["frame"] for x in r["candidates"]), 13)
        self.assertFalse(r["release_ready"])

    def test_semantically_verified_absence_stops(self):
        frames=clip()
        d=config(anchor=5,max_track=15)
        d["verified_absent"]=[{"frame":9,"participant":"guest","object":"bottle",
                               "semantic_verified":True,"provenance":"independent_visual_review"}]
        r=track(frames.__getitem__,d)
        self.assertLess(max(x["frame"] for x in r["candidates"]), 9)
        self.assertTrue(any(x["reason"]=="SEMANTICALLY_VERIFIED_ABSENT"
                            for x in r["abstentions"]))

    def test_seed_requires_independent_review(self):
        d=config()
        d["anchors"][0]["provenance"]="detector_guess"
        with self.assertRaises(ValueError):
            validate(d)

    def test_crossing_participant_roe_rejected(self):
        d=config()
        d["anchors"][0]["bbox"]=[98,28,115,52]
        with self.assertRaises(ValueError):
            validate(d)

    def test_featureless_seed_abstains(self):
        frames=clip(empty=True)
        frames=[np.full_like(a, 20) for a in frames]
        r=track(frames.__getitem__,config())
        self.assertEqual(r["candidate_mask_frames"],0)
        self.assertEqual(r["abstentions"][0]["reason"],"SEED_TOO_TEXTURELESS")

    def test_empty_anchor_list_never_means_no_objects(self):
        d=config()
        d["anchors"]=[]
        frames=clip()
        r=track(frames.__getitem__,d)
        self.assertEqual(r["candidate_mask_frames"],0)
        self.assertTrue(r["no_object_found_does_not_mean_absent"])
        self.assertFalse(r["release_ready"])

    def test_wrong_video_shape_rejected(self):
        d=config()
        frames=clip()
        frames[5]=np.zeros((180,400,3),np.uint8)
        with self.assertRaises(ValueError):
            track(frames.__getitem__,d)

    def test_detector_cannot_mark_negative_semantics(self):
        d=config()
        d["verified_absent"]=[{"frame":12,"participant":"guest","object":"bottle",
                              "semantic_verified":True,"provenance":"detector_guess"}]
        with self.assertRaises(ValueError):
            validate(d)

    def test_unverified_semantics_cannot_authorize_seed(self):
        d=config()
        d["anchors"][0]["semantic_verified"]=False
        with self.assertRaises(ValueError):
            validate(d)

    def test_cut_ambiguous_mask_is_never_exported(self):
        frames=clip(cut_at=10)
        d=config(anchor=9,cuts=[10],max_track=15)
        r=track(frames.__getitem__,d)
        for row in r["candidates"]:
            self.assertTrue(row["start"] < 10)
            self.assertEqual(row["end"],row["start"]+1)
        self.assertEqual(r["status"],"SHADOW_CANDIDATES_UNVERIFIED")


if __name__=="__main__":
    unittest.main()
