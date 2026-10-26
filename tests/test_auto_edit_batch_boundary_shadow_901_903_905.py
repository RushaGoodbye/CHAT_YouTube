"""Regression fixtures for read-only multi-stream Premiere boundary inspection."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

FILE=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"batch_boundary_shadow_901_903_905_v1.py"
spec=importlib.util.spec_from_file_location("batch_boundary_shadow",FILE)
b=importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

XML="""<xmeml><sequence><rate><timebase>30</timebase></rate><media>
<video><track><clipitem><in>100</in><out>400</out></clipitem></track></video>
<audio><track><clipitem><in>100</in><out>400</out></clipitem></track></audio>
</media></sequence></xmeml>"""

def make_inputs(root):
    for stream in b.TARGETS:
        rows=[]
        total=6 if stream in ("901","903") else 5
        for i in range(1,total+1):
            if stream=="903" and i in (2,5):continue
            name=f"RG_EDITED_{stream}_{i}.xml"
            path=root/stream/name
            path.parent.mkdir(exist_ok=True)
            path.write_text(XML,encoding="utf-8")
            rows.append({"index":i,"premiere_xml":str(path),"screenshot":f"{stream}-{i}.jpg"})
        manifest={"stream":stream,"dialogue_count":total,
                  "status":"PARTIAL_REVIEW" if stream=="903" else "DIALOGUES_COMPLETE",
                  "outputs":rows}
        if stream=="903":
            manifest["review_holds"]=[{"index":2,"status":"HOLD_FOR_REVIEW"},
                                      {"index":5,"status":"HOLD_FOR_REVIEW"}]
        (root/f"RG_EDITED_{stream}_MULTI_DIALOGUE.json").write_text(json.dumps(manifest),encoding="utf-8")
        qa={"stream":stream,"passed":False,"xml_count":len(rows),"checks":[]}
        (root/stream/"RG_POSTRUN_QA.json").write_text(json.dumps(qa),encoding="utf-8")
        if stream=="901":
            spans={1:(10,100),2:(110,200),3:(210,300),4:(365891,371616),
                   5:(366773,375966),6:(372083,407505)}
        elif stream=="905":
            spans={1:(158024,167920),2:(167719,189536),3:(190000,200000),
                   4:(201000,210000),5:(220000,240000)}
        else:continue
        issues=[{"code":"NEIGHBOUR_XML_SOURCE_OVERLAP","left":a,"right":c,"frames":frames}
                for (a,c),frames in b.EXPECTED_OVERLAPS[stream].items()]
        report={"passed":False,"issues":issues,"dialogues":[
            {"dialogue":i,"source_in":a,"source_out":end}
            for i,(a,end) in spans.items()]}
        (root/stream/"RG_BOUNDARY_QA_V51.json").write_text(json.dumps(report),encoding="utf-8")

class BatchBoundaryShadowTests(unittest.TestCase):
    def test_exact_overlap_interval_reconciliation(self):
        rows={"passed":False,
              "dialogues":[{"dialogue":1,"source_in":100,"source_out":400},
                           {"dialogue":2,"source_in":300,"source_out":700}],
              "issues":[{"code":"NEIGHBOUR_XML_SOURCE_OVERLAP","left":1,"right":2,"frames":100}]}
        result=b.analyze_interval_report(rows,{(1,2):100})
        self.assertEqual(result["overlaps"][0]["shared_source_frame_interval"],[300,400])
        self.assertFalse(result["overlaps"][0]["may_auto_trim"])

    def test_bad_report_cannot_authorize_trimming(self):
        rows={"passed":False,
              "dialogues":[{"dialogue":1,"source_in":100,"source_out":400},
                           {"dialogue":2,"source_in":300,"source_out":700}],
              "issues":[{"code":"NEIGHBOUR_XML_SOURCE_OVERLAP","left":1,"right":2,"frames":50}]}
        with self.assertRaisesRegex(RuntimeError,"contradicts"):
            b.analyze_interval_report(rows,{(1,2):50})

    def test_real_regression_shapes_in_one_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            make_inputs(root)
            evidence=b.shadow(root)
            self.assertEqual(sorted(evidence["streams"]),["901","903","905"])
            self.assertEqual(evidence["streams"]["901"]["boundary"]["overlaps"][0]["overlap_frames"],4843)
            self.assertEqual(evidence["streams"]["905"]["boundary"]["overlaps"][0]["overlap_frames"],201)
            self.assertEqual(evidence["streams"]["903"]["held_dialogues"],[2,5])
            self.assertFalse(evidence["automated_approval"])
            self.assertEqual(evidence["streams"]["901"]["xml"][0]["audio_tracks"],1)

    def test_changed_903_identity_hold_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            make_inputs(root)
            p=root/"RG_EDITED_903_MULTI_DIALOGUE.json"
            obj=json.loads(p.read_text(encoding="utf-8"))
            obj["review_holds"][1]["index"]=6
            p.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"held dialogue set"):
                b.shadow(root)

    def test_script_never_mutates_video_xml_or_qa(self):
        txt=FILE.read_text(encoding="utf-8")
        self.assertNotIn("write_text(",txt)
        self.assertNotIn("os.replace(",txt)
        self.assertNotIn("unlink(",txt)
        self.assertIn('"automated_approval": False',txt)

if __name__=="__main__":
    unittest.main()
