from pathlib import Path
import tempfile
import unittest

from rg_stability_readonly import review_qa, queue_audit, plan_recovery, TARGETS

class StabilityTests(unittest.TestCase):
    def test_qa_unverified_not_pass(self):
        self.assertEqual(review_qa({})["status"], "NOT_CHECKED")
        self.assertEqual(review_qa({"passed": True, "checks": []})["status"], "NOT_CHECKED")
        self.assertEqual(review_qa({"passed": True, "checks":[{"name":"audio","ok":False}]})["status"],"FAIL")

    def test_qa_confirmed_pass(self):
        self.assertEqual(review_qa({"passed":True,"checks":[{"name":"xml","ok":True}]})["status"],"PASS")

    def test_queue_not_armed(self):
        self.assertEqual(queue_audit({"queue":list(TARGETS),"full_recalc_targets":[]})["status"],"REVIEW")
        self.assertEqual(queue_audit({"queue":list(TARGETS),"full_recalc_targets":list(TARGETS)})["status"],"READY")

    def test_minimal_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"884.xml"
            path.write_text("XML",encoding="utf-8")
            manifest={"status":"DIALOGUES_COMPLETE","dialogue_count":1,"completed_dialogues":1}
            failed={"passed":False,"checks":[{"name":"postrun","ok":False}]}
            self.assertEqual(plan_recovery(stream="884",manifest=manifest,qa_report=failed,xml_paths=[path])["action"],"QA_ONLY_RECHECK")
            passed={"passed":True,"checks":[{"name":"xml","ok":True}]}
            self.assertEqual(plan_recovery(stream="884",manifest=manifest,qa_report=passed,xml_paths=[path])["action"],"NO_ACTION")
            manifest["completed_dialogues"]=0
            self.assertEqual(plan_recovery(stream="884",manifest=manifest,qa_report={},xml_paths=[path])["action"],"RESUME_IN_STUDIO")
            path.unlink()
            self.assertEqual(plan_recovery(stream="884",manifest=manifest,qa_report={},xml_paths=[path])["action"],"INVESTIGATE_INPUTS")

if __name__=="__main__":
    unittest.main()
