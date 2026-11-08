"""RG Auto Edit Studio: read-only output inventory and release evidence.

This tool never modifies media or runs editing workers.
"""
from __future__ import annotations

import json
from pathlib import Path

REQUIRED_OUTPUT_TYPES = ("premiere_xml",)


def audit_outputs(manifest: dict, qa: dict) -> dict:
    rows=manifest.get("outputs") or []
    if not isinstance(rows,list):
        return {"status":"FAIL","reason":"invalid output manifest","dialogues":[]}
    summary=[]
    for row in rows:
        if not isinstance(row,dict):
            summary.append({"status":"FAIL","reason":"invalid dialogue row"})
            continue
        xml=row.get("premiere_xml") or row.get("xml")
        exists=False
        bytes_count=0
        if xml:
            try:
                path=Path(xml)
                exists=path.is_file()
                bytes_count=path.stat().st_size if exists else 0
            except OSError:
                exists=False
        summary.append({"index":row.get("index"),
                        "xml_exists":exists,"xml_bytes":bytes_count,
                        "status":"PRESENT" if exists and bytes_count>0 else "MISSING"})
    expected=int(manifest.get("dialogue_count") or 0)
    manifest_complete=str(manifest.get("status") or "").upper()=="DIALOGUES_COMPLETE"
    qa_ok=qa.get("passed") is True and bool(qa.get("checks")) and all(
        isinstance(x,dict) and x.get("ok") is True for x in qa["checks"])
    files_ok=bool(summary) and all(row.get("status")=="PRESENT" for row in summary)
    inventory_ok=expected>0 and expected==len(summary) and manifest_complete
    # An XML file is not proof of QA: only explicit checks can release.
    status="PASS" if inventory_ok and files_ok and qa_ok else (
        "FAIL" if not files_ok and summary else "REVIEW")
    return {"status":status,"expected_dialogues":expected,
            "found_dialogues":len(summary),"files_ok":files_ok,
            "manifest_complete":manifest_complete,"qa_confirmed":qa_ok,
            "dialogues":summary}


def summarize_batch(items:list[dict]) -> dict:
    result={"PASS":0,"REVIEW":0,"FAIL":0}
    for item in items:
        status=str(item.get("status") or "REVIEW")
        result[status if status in result else "REVIEW"]+=1
    return {"total":len(items),"results":result,
            "unresolved":len(items)-result["PASS"]}
