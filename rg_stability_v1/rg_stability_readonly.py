"""RG Studio Stability V1: read-only diagnosis, release gate, and recovery planning.

Never launches a video process; never edits source media, XML or working queue.
The caller performs any authorized action through Studio only.
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any

REQUIRED_CHECK_CATEGORIES = ("xml", "boundary", "audio", "premiere")
TARGETS = tuple(str(x) for x in (885,891,892,893,898,901,902,903,904,905,907,908,909,910,911,912,913,914,915))


def load_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def review_qa(report: dict) -> dict:
    """Distinguish unverified, failed, and valid QA; fail closed."""
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        return {"status":"NOT_CHECKED", "passed":0,"total":0,"failed":[]}
    failed=[]
    verified=0
    for c in checks:
        if not isinstance(c, dict):
            failed.append("malformed-check")
            continue
        label = str(c.get("name") or "unnamed")
        if c.get("ok") is True:
            verified += 1
        else:
            failed.append(label)
    if failed or report.get("passed") is False:
        status = "FAIL"
    elif report.get("passed") is True and verified == len(checks):
        status = "PASS"
    else:
        status = "NOT_CHECKED"
    return {"status":status, "passed":verified,"total":len(checks),"failed":failed}


def plan_recovery(*, stream: str, manifest: dict, qa_report: dict, xml_paths: list[Path]) -> dict:
    """No action is automatic. Return an advised least-destructive next step."""
    status=str(manifest.get("status") or "").upper()
    qa=review_qa(qa_report)
    outputs=[Path(x) for x in xml_paths]
    xml_present=bool(outputs) and all(x.is_file() and x.stat().st_size>0 for x in outputs)
    expected=int(manifest.get("dialogue_count") or 0)
    completed=int(manifest.get("completed_dialogues") or 0)
    complete=expected>0 and expected==completed and status in ("DIALOGUES_COMPLETE","COMPLETE","DONE")
    if qa["status"]=="PASS" and complete and xml_present:
        action="NO_ACTION"
        reason="Current XML and confirmed QA already complete"
    elif xml_present and complete:
        action="QA_ONLY_RECHECK"
        reason="Existing completed XML must be preserved; only repeat failed QA"
    elif xml_present:
        action="RESUME_IN_STUDIO"
        reason="Partial output exists: inspect checkpoint and resume only missing stages"
    else:
        action="INVESTIGATE_INPUTS"
        reason="No verified XML available; recheck input and checkpoints before montage"
    return {"stream":str(stream),"action":action,"reason":reason,
            "xml_present":xml_present,"manifest_status":status,"qa":qa,
            "start_video_processing":False}


def queue_audit(queue_data: dict, expected:tuple[str,...]=TARGETS) -> dict:
    queue=[str(x) for x in (queue_data.get("queue") or [])]
    targets=[str(x) for x in (queue_data.get("full_recalc_targets") or [])]
    matches=queue==list(expected)
    armed=targets==list(expected)
    return {"status":"READY" if matches and armed else "REVIEW",
            "count":len(queue),"exact_order":matches,"recalc_armed":armed,
            "duplicates":len(queue)!=len(set(queue)),
            "running":bool(queue_data.get("running")),
            "queue":queue}


def report_for_stream(app:Path, stream:str) -> dict:
    stream=str(stream)
    manifest=load_json(app/f"RG_EDITED_{stream}_MULTI_DIALOGUE.json")
    qa=load_json(app/stream/"RG_POSTRUN_QA.json")
    xmls=[]
    for item in manifest.get("outputs") or []:
        if isinstance(item,dict):
            value=item.get("premiere_xml") or item.get("xml")
            if value:xmls.append(Path(value))
    return plan_recovery(stream=stream,manifest=manifest,qa_report=qa,xml_paths=xmls)


def main() -> None:
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--app",type=Path,required=True)
    ap.add_argument("--queue",type=Path,required=True)
    args=ap.parse_args()
    out={"schema":"RG_STABILITY_V1_READ_ONLY",
         "queue":queue_audit(load_json(args.queue)),
         "streams":[report_for_stream(args.app,s) for s in TARGETS]}
    print(json.dumps(out,ensure_ascii=True,indent=2))


if __name__=="__main__":
    main()
