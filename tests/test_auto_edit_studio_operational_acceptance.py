import importlib.util
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location(
    "studio_acceptance",Path(__file__).resolve().parents[1]/
    "rg_remote_control"/"auto_edit_features"/"studio_operational_acceptance_v1.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

XML="""<?xml version="1.0"?><xmeml><sequence><media>
<video><track><clipitem><name>sample</name></clipitem></track></video>
<audio><track><clipitem><name>audio</name></clipitem></track></audio>
</media></sequence></xmeml>"""+" "*500

class AcceptanceTests(unittest.TestCase):
    def test_review_manifest_keeps_xmls_without_promoting_complete(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"1.xml"
            p.write_text(XML,encoding="utf-8")
            doc={"stream":"903","status":"PARTIAL_REVIEW","dialogue_count":2,
                 "outputs":[{"index":1,"xml":str(p)}],
                 "review_holds":[{"index":2,"status":"HOLD_FOR_REVIEW"}]}
            v=m.check_manifest(doc)
            self.assertEqual(v["state"],"PARTIAL_REVIEW")
            self.assertEqual(v["held_indices"],[2])
            doc["review_holds"]=[]
            self.assertEqual(m.check_manifest(doc)["state"],"REVIEW_OR_BROKEN")

    def test_valid_xml_tracked_and_missing_audio_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"1.xml"
            p.write_text(XML,encoding="utf-8")
            self.assertTrue(m.xml_readonly(p)["structure_ok"])
            p.write_text(XML.replace("<audio>","<sound>").replace("</audio>","</sound>"),encoding="utf-8")
            self.assertFalse(m.xml_readonly(p)["structure_ok"])

    def test_never_promote_missing_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            r=m.inspect(Path(d))
            self.assertEqual(r["operational_gate"],"BACKEND_SOURCE_NOT_VERIFIED")
            self.assertFalse(r["gui_responsiveness_tested"])
            self.assertTrue(all(v["state"]=="MANIFEST_UNAVAILABLE"
                                for v in r["stream_manifests"].values()))
if __name__=="__main__":
    unittest.main()
