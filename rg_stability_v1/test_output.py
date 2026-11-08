from pathlib import Path
import tempfile
import unittest
from rg_output_audit import audit_outputs, summarize_batch

class OutputTests(unittest.TestCase):
    def test_reject_unverified_xml(self):
        with tempfile.TemporaryDirectory() as d:
            xml=Path(d)/"885.xml";xml.write_text("<xml/>",encoding="utf-8")
            m={"status":"DIALOGUES_COMPLETE","dialogue_count":1,
               "outputs":[{"index":1,"premiere_xml":str(xml)}]}
            self.assertEqual(audit_outputs(m,{})["status"],"REVIEW")
            self.assertEqual(audit_outputs(m,{"passed":True,"checks":[]})["status"],"REVIEW")
            self.assertEqual(audit_outputs(m,{"passed":True,"checks":[{"name":"xml","ok":True}]})["status"],"PASS")
            xml.unlink()
            self.assertEqual(audit_outputs(m,{"passed":True,"checks":[{"name":"xml","ok":True}]})["status"],"FAIL")
    def test_batch_totals(self):
        self.assertEqual(summarize_batch([{"status":"PASS"},{"status":"FAIL"},{"status":"REVIEW"}])["unresolved"],2)

if __name__=="__main__":unittest.main()
