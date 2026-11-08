"""Non-destructive nightly readiness report for existing Studio outputs."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from rg_stability_readonly import TARGETS, load_json, report_for_stream
from rg_output_audit import audit_outputs,summarize_batch

def build_report(app:Path, queue_file:Path, streams=TARGETS)->dict:
    queue=load_json(queue_file)
    rows={str(x.get("stream")):x for x in queue.get("rows",[]) if isinstance(x,dict)}
    findings=[]
    for stream in streams:
        recovery=report_for_stream(app,stream)
        manifest=load_json(app/f"RG_EDITED_{stream}_MULTI_DIALOGUE.json")
        qa=load_json(app/stream/"RG_POSTRUN_QA.json")
        output=audit_outputs(manifest,qa)
        row=rows.get(str(stream),{})
        findings.append({"stream":str(stream),"queue_status":row.get("status") or "UNKNOWN",
                         "stage":row.get("stage") or "UNKNOWN",
                         "recovery":recovery["action"],
                         "release_status":output["status"],
                         "xml_count":output["found_dialogues"],
                         "qa_confirmed":output["qa_confirmed"]})
    return {"schema":"RG_STABILITY_V1_NIGHTLY_READONLY",
            "queue_running":bool(queue.get("running")),
            "streams":findings,
            "totals":summarize_batch([{"status":x["release_status"]} for x in findings]),
            "live_workers_modified":False}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--app",required=True,type=Path)
    ap.add_argument("--queue",required=True,type=Path)
    a=ap.parse_args()
    print(json.dumps(build_report(a.app,a.queue),ensure_ascii=True,indent=2))

if __name__=="__main__":
    main()
