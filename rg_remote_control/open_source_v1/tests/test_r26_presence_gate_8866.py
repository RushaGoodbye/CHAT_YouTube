#!/usr/bin/env python3
"""R26 offline regression tests. Does not read source videos or change Studio."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r26_presence_gate_8866 import SCHEMA, evaluate


def fixture():
    required = [{"participant": "guest", "object": "bottle"},
                {"participant": "host", "object": "cigarette"}]
    rows = []
    for frame in range(6):
        rows += [
            {"frame": frame, "participant": "guest", "object": "bottle",
             "presence": "present" if frame in (1, 2) else "absent",
             "bbox": [60, 10, 80, 30] if frame in (1, 2) else None,
             "semantic_verified": True},
            {"frame": frame, "participant": "host", "object": "cigarette",
             "presence": "absent", "semantic_verified": True},
        ]
    return {
        "schema": SCHEMA, "frame_count": 6, "width": 100, "height": 50,
        "required_pairs": required, "cut_frames": [4],
        "evidence": rows, "masks": [
            {"start": 1, "end": 3, "participant": "guest",
             "object": "bottle", "bbox": [58, 8, 82, 32]}
        ],
    }


class R26GateTests(unittest.TestCase):
    def test_full_coverage_and_negative_evidence(self):
        result = evaluate(fixture())
        self.assertTrue(result["structural_candidate_pass"])
        self.assertEqual(result["semantically_reviewed_object_frames"], 12)
        self.assertEqual(result["unknown_object_frames"], 0)
        self.assertEqual(result["confirmed_covered_object_frames"], 2)
        self.assertEqual(result["issue_count"], 0)
        self.assertFalse(result["release_ready"])
        self.assertFalse(result["video_pixel_qa_pass"])

    def test_one_visible_frame_without_blur_fails(self):
        d = fixture()
        d["masks"][0]["end"] = 2
        result = evaluate(d)
        self.assertFalse(result["structural_candidate_pass"])
        self.assertEqual(result["visible_object_uncovered_frames"], 1)

    def test_extra_blur_after_bottle_disappears_fails(self):
        d = fixture()
        d["masks"][0]["end"] = 4
        result = evaluate(d)
        self.assertEqual(result["mask_on_confirmed_absence_frames"], 1)
        self.assertIn("MASK_WHEN_OBJECT_ABSENT", result["issues_by_kind"])

    def test_unknown_is_not_absent(self):
        d = fixture()
        d["evidence"] = [row for row in d["evidence"]
                         if not (row["frame"] == 1 and row["participant"] == "guest")]
        result = evaluate(d)
        self.assertEqual(result["unknown_object_frames"], 1)
        self.assertIn("MASK_WITHOUT_VERIFIED_OBJECT_PRESENCE", result["issues_by_kind"])

    def test_detector_claim_is_not_semantic_confirmation(self):
        d = fixture()
        d["evidence"][2]["semantic_verified"] = False
        result = evaluate(d)
        self.assertEqual(result["unknown_object_frames"], 1)
        self.assertFalse(result["structural_candidate_pass"])

    def test_cross_cut_masks_rejected(self):
        d = fixture()
        d["cut_frames"] = [2, 4]
        result = evaluate(d)
        self.assertIn("MASK_CROSSES_CUT", result["issues_by_kind"])

    def test_wrong_position_fails_even_if_time_matches(self):
        d = fixture()
        d["masks"][0]["bbox"] = [5, 5, 20, 20]
        result = evaluate(d)
        self.assertEqual(result["visible_object_uncovered_frames"], 2)

    def test_preserve_microphone_and_cup(self):
        d = fixture()
        d["protected_evidence"] = [
            {"frame": 1, "participant": "guest", "object": "microphone",
             "bbox": [60, 10, 75, 25], "semantic_verified": True},
            {"frame": 2, "participant": "guest", "object": "cup",
             "bbox": [62, 11, 72, 22], "semantic_verified": True},
        ]
        result = evaluate(d)
        self.assertEqual(result["protected_overlap_events"], 2)
        self.assertFalse(result["structural_candidate_pass"])

    def test_duplicate_evidence_rejected(self):
        d = fixture()
        d["evidence"].append(copy.deepcopy(d["evidence"][0]))
        with self.assertRaises(ValueError):
            evaluate(d)

    def test_invalid_bbox_rejected(self):
        d = fixture()
        d["masks"][0]["bbox"] = [-1, 5, 20, 20]
        with self.assertRaises(ValueError):
            evaluate(d)

    def test_missing_required_pairs_rejected(self):
        d = fixture()
        d["required_pairs"] = []
        with self.assertRaises(ValueError):
            evaluate(d)

    def test_never_authorize_release_with_structural_pass(self):
        result = evaluate(fixture())
        self.assertTrue(result["structural_candidate_pass"])
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["audio_bit_exact_verified"], False)
        self.assertIs(result["video_pixel_qa_pass"], False)


if __name__ == "__main__":
    unittest.main()
