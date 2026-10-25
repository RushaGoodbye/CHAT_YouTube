import importlib.util
from pathlib import Path
import unittest

SOURCE=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"reconcile_903_queue_review_v1.py"
spec=importlib.util.spec_from_file_location("reconcile_903_queue_review",SOURCE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def fixture():
    manifest={"stream":"903","status":"PARTIAL_REVIEW","dialogue_count":6,
              "outputs":[{"index":i} for i in [1,3,4,6]],
              "review_holds":[{"index":i,"status":"HOLD_FOR_REVIEW"} for i in [2,5]]}
    qa={"stream":"903","passed":False,"xml_count":4,
        "checks":[{"name":k,"ok":True} for k in m.REQUIRED]}
    state={"schema":"RG_STUDIO_BATCH_UI_V2","running":False,"paused":False,
           "queue":["903","904"],
           "rows":[{"stream":"903","status":"ПОМИЛКА","stage":"ERROR","progress":"97%"},
                   {"stream":"904","status":"ГОТОВО","stage":"CHECKPOINT","progress":"100%"}]}
    return state,manifest,qa

class Reconcile903QueueReviewTest(unittest.TestCase):
    def test_exact_partial_4_plus_2_reconciles_only_903(self):
        state,manifest,qa=fixture()
        out,status=m.plan(state,manifest,qa)
        self.assertEqual(status,"PATCH_READY")
        self.assertEqual(out["rows"][0]["status"],"ПЕРЕВІРКА")
        self.assertEqual(out["rows"][0]["stage"],"IDENTITY_REVIEW")
        self.assertEqual(out["rows"][1],state["rows"][1])
        self.assertEqual(state["rows"][0]["status"],"ПОМИЛКА")
        self.assertEqual(m.plan(out,manifest,qa)[1],"ALREADY_REVIEW")

    def test_no_unsafe_approval_on_bad_qa(self):
        state,manifest,qa=fixture()
        qa["checks"][0]["ok"]=False
        with self.assertRaises(RuntimeError):
            m.plan(state,manifest,qa)

    def test_running_queue_never_modified(self):
        state,manifest,qa=fixture()
        state["running"]=True
        with self.assertRaises(RuntimeError):
            m.plan(state,manifest,qa)

    def test_cannot_promote_held_to_ready_or_missing_holds(self):
        state,manifest,qa=fixture()
        manifest["review_holds"]=[]
        with self.assertRaises(RuntimeError):
            m.plan(state,manifest,qa)

if __name__=="__main__":
    unittest.main()
