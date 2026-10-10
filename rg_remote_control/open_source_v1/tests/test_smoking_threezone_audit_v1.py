"""Synthetic regression tests for existing threezone ZIP audit; zero production files."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audit_smoking_threezone_zip_v1 import audit, SRC_SHA


class ThreeZoneZipAuditTests(unittest.TestCase):
    def fixtures(self, root, missing=None, early_mouth=False, broken_release=False):
        three = root / "three.zip"
        yunet = root / "yu.zip"
        arr = np.zeros((610, 740), np.uint8)
        arr[175:183, 248:260] = 255
        hand = np.zeros_like(arr)
        hand[179:240, 253:320] = 255
        cjpg = cv2.imencode(".png", arr)[1].tobytes()
        hjpg = cv2.imencode(".png", hand)[1].tobytes()
        area1 = int((arr > 0).sum())
        area2 = int((hand > 0).sum())
        rows = []
        yr = []
        with zipfile.ZipFile(three, "w", zipfile.ZIP_DEFLATED) as z:
            for i in range(60):
                a = f"cigar_masks/{i:02d}.png"
                b = f"hand_masks/{i:02d}.png"
                if a != missing: z.writestr(a, cjpg)
                z.writestr(b, hjpg)
                rows.append({
                    "source_frame": 360+i,
                    "cigar_pixels": area1,
                    "hand_pixels": area2,
                    "mouth_guide_pixels": 100 if early_mouth else 0,
                    "hand_contact_candidate_pixels": 150,
                    "union_pixels": 250,
                    "automatic_release_allowed": False,
                    "flags": [],
                })
                yr.append({
                    "frame_index": i,
                    "cigarette_sam2_centroid_xy": [1254, 420],
                    "distance_mouth_to_sam2_centroid_px": 200 if early_mouth else 50,
                })
            z.writestr("THREEZONE_892_UNAPPROVED_2S_NO_AUDIO.mp4", b"fake-test-only")
            z.writestr("metrics.csv", b"header\n")
            z.writestr("report.json", json.dumps({
                "schema": "RG_892_THREEZONE_CIGAR_HAND_MOUTH_SHADOW_V1",
                "source_sha256": SRC_SHA,
                "frames_total": 60,
                "source_frames": [360, 419],
                "studio_modified": False,
                "quarantine_886_5_unchanged": True,
                "smoke_detector_verified": False,
                "production_release_allowed": broken_release,
                "frames": rows,
            }))
        with zipfile.ZipFile(yunet, "w") as z:
            z.writestr("report.json", json.dumps({
                "schema": "RG_YUNET_892_REAL_MOUTH_LANDMARKS_SHADOW_V1",
                "source_frame_offset": 360,
                "production_release_allowed": False,
                "frames": yr,
            }))
        return three, yunet

    def test_valid_60_frame_archive_is_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = self.fixtures(Path(td))
            report = audit(a, b)
            self.assertEqual(report["total_frames_checked"], 60)
            self.assertEqual(report["cigarette_empty_frames"], 0)
            self.assertFalse(report["production_release_allowed"])
            self.assertFalse(report["smoke_detection_verified"])

    def test_missing_mask_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = self.fixtures(Path(td), "cigar_masks/19.png")
            with self.assertRaisesRegex(ValueError, "Missing required outputs"):
                audit(a, b)

    def test_distant_cigarette_cannot_silently_blur_mouth(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = self.fixtures(Path(td), early_mouth=True)
            d = audit(a, b)
            self.assertEqual(
                d["geometric_warning_counts"].get("MOUTH_BLUR_WHILE_CIGARETTE_FAR"), 60
            )

    def test_release_gate_must_be_explicitly_false(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = self.fixtures(Path(td), broken_release=True)
            with self.assertRaisesRegex(ValueError, "Production release"):
                audit(a, b)


if __name__ == "__main__":
    unittest.main()
