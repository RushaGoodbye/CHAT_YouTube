from pathlib import Path
import tempfile
import unittest
from rg_watchdog import WorkerObservation, decide_watchdog
from rg_resources import Resources, decide_resources
from rg_errors import classify_failure
from rg_xml_structural import audit_premiere_xml


class GuardTests(unittest.TestCase):
    def test_watchdog(self):
        self.assertEqual(decide_watchdog(WorkerObservation(False,1000,0,0,0))["status"],"IDLE")
        self.assertEqual(decide_watchdog(WorkerObservation(True,1000,950,940,920))["status"],"ACTIVE")
        self.assertEqual(decide_watchdog(WorkerObservation(True,1000,600,600,600))["status"],"SLOW")
        result=decide_watchdog(WorkerObservation(True,1000,0,0,0))
        self.assertEqual(result["status"],"SUSPECTED_STALL")
        self.assertNotIn("KILL",result["action"])
        self.assertEqual(decide_watchdog(WorkerObservation(True,1000,2000,0,0))["status"],"UNKNOWN")

    def test_resource_gate(self):
        ok=decide_resources(Resources(150,16,6,True,True))
        self.assertEqual(ok["status"],"READY")
        low=decide_resources(Resources(4,16,6,True,True))
        self.assertEqual(low["action"],"WARN_AND_PAUSE_AFTER_CURRENT")
        self.assertEqual(decide_resources(Resources(150,16,None,True,True))["status"],"REVIEW")
        self.assertEqual(decide_resources(Resources(150,16,6,True,False))["status"],"BLOCK_NEXT_LAUNCH")

    def test_error_routing(self):
        self.assertEqual(classify_failure("QA_REPORT_MISSING",xml_verified=True,manifest_complete=True,qa_failure_only=True)["action"],"QA_ONLY_RECHECK_IN_STUDIO")
        self.assertEqual(classify_failure("QA_REPORT_MISSING",xml_verified=False,manifest_complete=True,qa_failure_only=True)["action"],"MANUAL_DIAGNOSTIC")
        self.assertEqual(classify_failure("SCREENSHOTS_MISSING",xml_verified=False,manifest_complete=False)["status"],"SKIP_CURRENT")
        self.assertEqual(classify_failure("OUTPUT_ARCHIVE_FAILED",xml_verified=False,manifest_complete=False)["status"],"STOP_QUEUE")
        for code in ("QA_REPORT_MISSING","SCREENSHOTS_MISSING","OUTPUT_ARCHIVE_FAILED","OTHER"):
            self.assertFalse(classify_failure(code,xml_verified=True,manifest_complete=True).get("automatic_video_restart"))

    def test_xml_structural(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"premiere.xml"
            self.assertEqual(audit_premiere_xml(p)["status"],"FAIL")
            p.write_text("<broken",encoding="utf-8")
            self.assertIn("XML_PARSE_ERROR",audit_premiere_xml(p)["errors"])
            p.write_text("<xmeml><sequence><media><video><track><clipitem><start>0</start><end>50</end></clipitem></track></video><audio><track><clipitem><start>0</start><end>50</end></clipitem></track></audio></media></sequence></xmeml>",encoding="utf-8")
            r=audit_premiere_xml(p)
            self.assertEqual(r["status"],"REVIEW")
            self.assertFalse(r["premiere_visual_validation"])
            p.write_text("<xmeml><sequence><media><video><track><clipitem><start>55</start><end>50</end></clipitem></track></video></media></sequence></xmeml>",encoding="utf-8")
            self.assertEqual(audit_premiere_xml(p)["status"],"FAIL")

if __name__=="__main__":
    unittest.main()
