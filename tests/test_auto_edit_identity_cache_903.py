import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"identity_cache_shadow_903_v1.py"
spec=importlib.util.spec_from_file_location("identity_cache_shadow",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class IdentityCacheAuditTests(unittest.TestCase):
    def rows(self):
        return [
            {"time":3593.5,"state":"OTHER_FACE","best":0.1},
            {"time":3949.5,"state":"OTHER_FACE","best":0.3},
            {"time":3953.5,"state":"PLACEHOLDER","best":0},
            {"time":4200.0,"state":"CURRENT","best":0.7},
            {"time":4200.8,"state":"CURRENT","best":0.6},
            {"time":4313.5,"state":"OTHER_FACE","best":0.1}
        ]

    def test_nearest_anchor_is_not_false_current(self):
        out=mod.evidence(self.rows())
        self.assertTrue(out["valid"])
        self.assertEqual(out["CURRENT_total"],2)
        self.assertEqual(out["CURRENT_45s"],0)
        self.assertEqual(out["nearest_anchor"]["state"],"PLACEHOLDER")
        self.assertGreater(out["current_components"][0]["nearest_offset_sec"],200)

    def test_rejects_wrong_window(self):
        self.assertFalse(mod.evidence([{"time":1.,"state":"CURRENT"},{"time":2,"state":"CURRENT"}])["valid"])

    def test_no_production_write_actions(self):
        src=p.read_text(encoding="utf-8")
        self.assertIn('"media_writes":0',src)
        self.assertIn('"xml_writes":0',src)
        self.assertNotIn("write_text(",src)
        self.assertNotIn("unlink(",src)

if __name__=="__main__":
    unittest.main()
