import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"qa_verify_903_v1.py"
spec=importlib.util.spec_from_file_location("qa_verify_903_v1",SCRIPT)
qa=importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)

def manifest():
    return {
        "stream":"903","status":"PARTIAL_REVIEW","dialogue_count":6,
        "outputs":[{"index":i,"premiere_xml":f"RG_EDITED_903_{i}.xml"} for i in (1,3,4,6)],
        "review_holds":[{"index":2},{"index":5}],
    }

def report():
    return {"stream":"903","passed":False,"xml_count":4,
            "checks":[
                {"name":"Повнота діалогів","ok":False,
                 "detail":"MISSING PRIMARY XML: 2,5 • expected=1,2,3,4,5,6"},
                {"name":"XML створено","ok":True,"detail":"4 XML"},
                {"name":"Перевірка XML","ok":True},
                {"name":"Premiere сумісність","ok":True},
                {"name":"Контроль меж","ok":True},
            ]}

class QA903SafetyTests(unittest.TestCase):
    def test_expected_four_plus_two_holds(self):
        self.assertTrue(qa.validate_manifest(manifest()))
        self.assertTrue(qa.summarize(report())["valid_partial"])

    def test_nonmatching_hold_aborts(self):
        m=manifest()
        m["review_holds"]=[{"index":1},{"index":5}]
        with self.assertRaises(RuntimeError):
            qa.validate_manifest(m)

    def test_missing_xml_validation_aborts(self):
        r=report()
        r["checks"][2]["ok"]=False
        self.assertFalse(qa.summarize(r)["valid_partial"])

    def test_false_six_dialogue_pass_aborts(self):
        r=report()
        r["passed"]=True
        r["xml_count"]=6
        self.assertFalse(qa.summarize(r)["valid_partial"])

if __name__=="__main__":
    unittest.main()
