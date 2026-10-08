#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import scene_suggest
import oss_audit

class FakeTime:
    def __init__(self,sec):
        self.sec=sec
    def get_seconds(self):
        return self.sec

def scenes(*_args,**_kw):
    return [(FakeTime(10),FakeTime(20)),(FakeTime(20),FakeTime(50)),
            (FakeTime(50),FakeTime(100))]

class FakeDetector:
    def __init__(self):
        pass

class RGOSSIntegrationTests(unittest.TestCase):
    def test_window_closes_on_invalid(self):
        for x,y in [(-1,10),(0,0),(0,601),(0,float("nan")),(400000,2)]:
            with self.subTest(x=x,y=y):
                with self.assertRaises(ValueError):
                    scene_suggest.validate_window(x,y)
        self.assertEqual(scene_suggest.validate_window(10,90),(10,100))

    def test_candidates_are_never_automatic_dialogue_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/"886.mp4"
            video.write_bytes(b"fixture")
            res=scene_suggest.analyze(video,10,90,detector_fn=scenes,
                                      detector_class=FakeDetector)
            self.assertEqual(res["candidate_count"],2)
            self.assertEqual([r["at_source_sec"] for r in res["candidates"]],[20,50])
            self.assertFalse(res["production_applied"])
            self.assertFalse(res["source_audio_modified"])
            self.assertFalse(res["cigarette_blur_modified"])
            self.assertTrue(all(not r["dialogue_end"] for r in res["candidates"]))

    def test_malformed_timecodes_fail_closed(self):
        with self.assertRaises(ValueError):
            scene_suggest.suggest_cuts(
                [(FakeTime(20),FakeTime(10))],10,100)

    def test_only_isolated_output_folder_is_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"oss_shadow"
            other=Path(tmp)/"production.xml"
            safe=root/"scene_886.json"
            scene_suggest.save_shadow({"status":"SHADOW_PASS"},safe,root)
            self.assertEqual(json.loads(safe.read_text())["status"],"SHADOW_PASS")
            with self.assertRaises(ValueError):
                scene_suggest.save_shadow({},other,root)
            with self.assertRaises(ValueError):
                scene_suggest.save_shadow({},Path(tmp)/"escape.json",root)

    def test_catalog_license_gate_and_explicit_contour(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=oss_audit.report(app_root=Path(tmp))
            self.assertEqual(report["contour"],"auto_edit")
            self.assertTrue(report["read_only"])
            self.assertFalse(report["installation_attempted"])
            self.assertFalse(report["production_modified"])
            self.assertGreaterEqual(len(report["components"]),12)
            self.assertIn("ultralytics",report["known_licensing_review_required"])
            self.assertEqual(report["safety"]["cigarette_mandatory"],None)

    def test_registry_never_enables_agpl_or_noncommercial_module(self):
        reg=json.loads((HERE/"catalog.json").read_text(encoding="utf-8"))
        items={x["id"]:x for x in reg["components"]}
        self.assertIn("AGPL",items["ultralytics"]["license"])
        self.assertIn("CC-BY-NC",items["cotracker"]["license"])
        self.assertEqual(items["cotracker"]["status"],
                         "DO_NOT_INTEGRATE_FOR_MONETIZED_PRODUCTION")
        self.assertNotIn("PRODUCTION",items["pyscenedetect"]["status"])

if __name__=="__main__":
    unittest.main()
