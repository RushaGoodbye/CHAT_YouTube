import importlib.util,unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"selector_shadow_907_v1.py"
spec=importlib.util.spec_from_file_location("selector_shadow_907_v1",SCRIPT)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class SelectorShadowTests(unittest.TestCase):
    def test_real_visual_score_and_verified_anchor_required(self):
        self.assertTrue(mod.qualify({"time":4586.25,"score":.7533},4586.25))
        self.assertFalse(mod.qualify({"time":4938.5,"score":.7533},4586.25))
        self.assertFalse(mod.qualify({"time":4586.25,"score":.39},4586.25))
    def test_distinct_image_signatures(self):
        class Img:
            def __init__(self,v):self.v=v
            def tobytes(self):return self.v
        self.assertNotEqual(mod.fingerprint(Img(b"faceA")),mod.fingerprint(Img(b"faceB")))
    def test_no_installed_source_patching_or_media_writes(self):
        s=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"studio_source_patched":False',s)
        self.assertIn('"xml_writes":0',s)
        self.assertIn('clock._best_local_match=original_match',s)
        self.assertNotIn("os.replace(",s)
        self.assertNotIn("shutil.move(",s)
if __name__=="__main__":unittest.main()
