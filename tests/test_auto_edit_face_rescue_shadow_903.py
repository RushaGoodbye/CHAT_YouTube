import importlib.util
from pathlib import Path
from unittest import TestCase
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"rg_remote_control"/"auto_edit_features"/"face_rescue_shadow_903_v1.py"
spec=importlib.util.spec_from_file_location("face_rescue_shadow",PATH)
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class ShadowFaceRescueTests(TestCase):
    def test_valid_box_geometry(self):
        self.assertTrue(probe.valid_box([300,20,60,60],1000,600))
        self.assertFalse(probe.valid_box([300,20,5,60],1000,600))
        self.assertFalse(probe.valid_box([1100,20,60,60],1000,600))
        self.assertFalse(probe.valid_box([float("nan"),20,60,60],1000,600))

    def test_views_preserve_right_half_and_top(self):
        class FakeImage:
            shape=(600,1000,3)
            def __getitem__(self,key):
                class Slice:
                    shape=(420,500,3)
                return Slice()
        rows=probe.crop_views(FakeImage())
        self.assertEqual([x[0] for x in rows],
            ["top48","top70","right_top70","right_top100"])
        self.assertEqual(rows[2][2],500.)

    def test_probe_never_enables_model_downloads_or_media_changes(self):
        src=PATH.read_text(encoding="utf-8")
        self.assertIn("ensure_model(allow_download=False",src)
        self.assertIn('"auto_release":False',src)
        self.assertIn('"source_xml_changes":0',src)
        self.assertNotIn("download_models(",src)
        self.assertNotIn("write_text(",src)
        self.assertNotIn("unlink(",src)

if __name__=="__main__":
    unittest.main()
