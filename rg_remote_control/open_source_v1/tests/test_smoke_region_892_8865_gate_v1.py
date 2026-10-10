"""Smoke QA gate tests. Synthetic masks only; never production approval."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import smoke_region_892_8865_release_gate_v1 as mod


class Smoke886HardNegativeTests(unittest.TestCase):
    def build(self,root):
        frame=np.zeros((610,740),np.uint8)
        frame[10,200]=255
        png=cv2.imencode(".png",frame)[1].tobytes()
        blank=cv2.imencode(".png",np.zeros_like(frame))[1].tobytes()
        neg=root/"886_review.json"
        neg.write_text(json.dumps({
           "schema":mod.NEG, "real_source_images_processed":101,
           "full_negative_8865_video_test":False,
           "quarantine_886_5_unchanged":True
        }),encoding="utf-8")
        p=root/"V3B.zip"
        rows=[]
        with zipfile.ZipFile(p,"w") as z:
            for i in range(60):
                missing = i in (0,10,20)
                content=blank if missing else png
                z.writestr(f"masks/smoke_unverified_{i:02d}.png",content)
                rows.append({
                    "source_frame":i+360,
                    "smoke_motion_candidate_pixels":0 if missing else 1,
                })
            z.writestr("report.json",json.dumps({
                "schema":mod.V3B,
                "production_release_allowed":False,
                "smoke_identification_verified":False,
                "negative_8865_test_passed":False,
                "rows":rows
            }))
        return p, neg

    def test_realistic_missing_regions_hold_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,neg=self.build(Path(tmp))
            r=mod.audit(p,neg)
            self.assertFalse(r["production_release_allowed"])
            self.assertEqual(r["smoke_coarse_region_count"],7)
            self.assertGreaterEqual(r["empty_smoke_region_count"],4)
            self.assertFalse(r["8865_full_negative_video_test_passed"])

    def test_corrupted_negative_claim_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,neg=self.build(Path(tmp))
            d=json.loads(neg.read_text())
            d["full_negative_8865_video_test"]=True
            neg.write_text(json.dumps(d))
            with self.assertRaisesRegex(ValueError,"886_5"):
                mod.audit(p,neg)

    def test_shape_error_rejected(self):
        with self.assertRaises(ValueError):
            mod.in_box(np.zeros((610,740)),(5,5,1,2))


if __name__=="__main__":
    unittest.main()
