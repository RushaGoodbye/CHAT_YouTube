"""Fail-closed contract tests for the isolated 892 three-zone preview."""
import ast
import pathlib
import sys
import unittest

import numpy as np

SRC = pathlib.Path(__file__).resolve().parents[1] / "smoking_threezone_892_shadow_v1.py"
sys.path.insert(0, str(SRC.parent))
import smoking_threezone_892_shadow_v1 as mod


class ThreeZoneShadowTests(unittest.TestCase):
    def setUp(self):
        self.cigar = np.zeros((160, 220), dtype=np.uint8)
        self.cigar[72:80, 100:110] = 1
        self.hand = np.zeros_like(self.cigar)
        self.hand[76:122, 107:145] = 1
        self.hand[0:10, 0:10] = 1

    def test_nearby_fingers_are_local_only(self):
        cigarette, contact, mouth, flags = mod.zones(
            self.cigar, self.hand, (1106, 318), .95
        )
        self.assertGreater(int(cigarette.sum()), 0)
        self.assertGreater(int(contact.sum()), 0)
        self.assertEqual(int(contact[2, 2]), 0)
        self.assertGreater(int(mouth.sum()), 0)
        self.assertIn("MOUTH_HEURISTIC_NOT_PIXEL_VERIFIED", flags)

    def test_empty_cigarette_mask_prevents_all_three_zones(self):
        a, b, c, flags = mod.zones(
            np.zeros_like(self.cigar), self.hand, (1106, 318), .99
        )
        self.assertFalse(a.any() or b.any() or c.any())
        self.assertIn("CIGARETTE_MASK_EMPTY", flags)

    def test_low_confidence_yunet_is_not_used_as_mouth(self):
        a, b, c, flags = mod.zones(self.cigar, self.hand, (1106, 318), .69)
        self.assertFalse(c.any())
        self.assertIn("MOUTH_LANDMARK_UNRELIABLE", flags)

    def test_far_mouth_is_excluded(self):
        a, b, c, flags = mod.zones(self.cigar, self.hand, (1200, 390), .95)
        self.assertFalse(c.any())
        self.assertIn("MOUTH_NOT_NEAR_CIGARETTE", flags)

    def test_outside_roi_mouth_is_excluded(self):
        a, b, c, flags = mod.zones(self.cigar, self.hand, (1300, 500), .95)
        self.assertFalse(c.any())
        self.assertIn("MOUTH_OUTSIDE_ROI", flags)

    def test_rejects_shape_mismatch(self):
        with self.assertRaises(RuntimeError):
            mod.zones(self.cigar, np.zeros((50, 50), np.uint8), None, None)

    def test_immutable_outputs_and_release_gate(self):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        text = SRC.read_text(encoding="utf-8")
        self.assertIn('"production_release_allowed":False', text)
        self.assertIn('"smoke_detector_verified":False', text)
        self.assertIn('sha(HOLD)!=hold_hash', text)
        self.assertIn('sha(SRC)!=SRC_SHA', text)
        self.assertIn('"886_5 quarantine invalid', text)
        self.assertIn('OUT.exists()', text)
        self.assertTrue(any(
            isinstance(node, ast.FunctionDef) and node.name == "validate"
            for node in ast.walk(tree)
        ))


if __name__ == "__main__":
    unittest.main()
