import importlib.util
from pathlib import Path
import tempfile
import unittest

p=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"reconcile_903_5of6_queue_v1.py"
spec=importlib.util.spec_from_file_location("reconcile_903",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class QueueReconcileTests(unittest.TestCase):
    def create(self,folder):
        outputs=[]
        for n in [1,2,3,4,6]:
            file=folder/("903_"+str(n)+".xml")
            file.write_text("<xml/>",encoding="utf-8")
            outputs.append({"index":n,"xml":str(file)})
        return {"stream":"903","status":"PARTIAL_REVIEW","dialogue_count":6,
                "outputs":outputs,"review_holds":[{"index":5,"status":"HOLD_FOR_REVIEW"}]}

    def test_5_of_6_queues_held_not_complete_and_other_rows_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            doc=self.create(Path(d))
            original={"schema":"RG_STUDIO_BATCH_UI_V2","running":False,"paused":False,
                      "rows":[{"stream":"903","status":"ПЕРЕВІРКА","stage":"IDENTITY_REVIEW",
                               "detail":m.OLD_LABEL,"progress":"67%"},
                              {"stream":"907","status":"ПОМИЛКА","stage":"ERROR"}]}
            out,mode=m.proposed_state(original,doc)
            self.assertEqual(mode,"PATCH_READY")
            self.assertEqual(out["rows"][0]["detail"],m.NEW_LABEL)
            self.assertEqual(out["rows"][0]["progress"],"83%")
            self.assertEqual(out["rows"][0]["status"],"ПЕРЕВІРКА")
            self.assertEqual(out["rows"][1],original["rows"][1])
            self.assertEqual(m.proposed_state(out,doc)[1],"ALREADY_CURRENT")
            self.assertEqual(original["rows"][0]["detail"],m.OLD_LABEL)

    def test_refuse_any_incomplete_evidence_or_active_queue(self):
        with tempfile.TemporaryDirectory() as d:
            doc=self.create(Path(d))
            queue={"schema":"RG_STUDIO_BATCH_UI_V2","running":True,"paused":False,
                   "rows":[{"stream":"903","status":"ПЕРЕВІРКА",
                            "stage":"IDENTITY_REVIEW","detail":m.OLD_LABEL}]}
            with self.assertRaisesRegex(RuntimeError,"Live/paused"):
                m.proposed_state(queue,doc)
            queue["running"]=False
            doc["review_holds"]=[]
            with self.assertRaisesRegex(RuntimeError,"does not prove 5/6"):
                m.proposed_state(queue,doc)

if __name__=="__main__":
    unittest.main()
