import importlib.util
from pathlib import Path
import unittest

SOURCE=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"reconcile_boundary_review_901_905_v1.py"
spec=importlib.util.spec_from_file_location("reconcile_boundary_review",SOURCE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def fixture():
    state={"schema":"RG_STUDIO_BATCH_UI_V2","running":False,"paused":False,
        "rows":[{"stream":"901","status":"ГОТОВО","stage":"CHECKPOINT"},
                {"stream":"904","status":"ГОТОВО","stage":"CHECKPOINT"},
                {"stream":"905","status":"ГОТОВО","stage":"CHECKPOINT"}]}
    evidence={}
    for stream,overlap in m.PAIRS.items():
        count=6 if stream=="901" else 5
        manifest={"stream":stream,"status":"DIALOGUES_COMPLETE","dialogue_count":count,
                  "outputs":[{"premiere_xml":f"RG_EDITED_{stream}_{i}.xml"} for i in range(1,count+1)]}
        qa={"stream":stream,"passed":False,"xml_count":count,
            "checks":[{"name":"Перевірка XML","ok":False,"critical":True},
                      {"name":"Контроль меж","ok":False,"critical":True}]}
        boundary={"passed":False,"issues":[
            {"code":"NEIGHBOUR_XML_SOURCE_OVERLAP","left":a,"right":b,"frames":n}
            for (a,b),n in overlap.items()]}
        evidence[stream]=(manifest,qa,boundary)
    return state,evidence

class BoundaryQueueReviewTests(unittest.TestCase):
    def test_change_only_problem_streams(self):
        state,ev=fixture()
        fixed,changes=m.plan(state,ev)
        self.assertEqual(set(changes),{"901","905"})
        self.assertEqual(fixed["rows"][1],state["rows"][1])
        self.assertEqual(fixed["rows"][0]["status"],"ПЕРЕВІРКА")
        self.assertIn("4843",fixed["rows"][0]["detail"])
        self.assertIn("201",fixed["rows"][2]["detail"])
        self.assertEqual(m.plan(fixed,ev)[1],[])

    def test_queue_running_refuses(self):
        state,ev=fixture();state["running"]=True
        with self.assertRaises(RuntimeError):
            m.plan(state,ev)

    def test_changed_overlap_refuses(self):
        state,ev=fixture();ev["905"][2]["issues"][0]["frames"]=100
        with self.assertRaises(RuntimeError):
            m.plan(state,ev)

    def test_passed_qa_refuses_to_mark_review(self):
        state,ev=fixture();ev["901"][1]["passed"]=True
        with self.assertRaises(RuntimeError):
            m.plan(state,ev)

if __name__=="__main__":
    unittest.main()
