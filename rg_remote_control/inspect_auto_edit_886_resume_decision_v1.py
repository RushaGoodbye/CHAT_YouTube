#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only, compact evidence for 886 dialogue numbering and safe resume."""
from __future__ import annotations
import json
import pathlib
import re
import time
from collections import Counter

APP = pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA = pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")

def read_text(p):
    try:
        return p.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as exc:
        return "READ_ERROR: " + str(exc)

def outputs():
    rows = []
    for folder in [APP, APP / "886"]:
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("RG_EDITED_886*.xml")):
            if re.fullmatch(r"RG_EDITED_886(?:_\d+)?\.xml", p.name, re.I):
                st = p.stat()
                rows.append({
                    "path": str(p), "name": p.name, "size": st.st_size,
                    "mtime_epoch": round(st.st_mtime, 3),
                })
    return rows

def resume_source():
    p = APP / "rg_multi_dialogue.py"
    result = {"path": str(p), "exists": p.is_file()}
    if not p.is_file():
        return result
    lines = read_text(p).splitlines()
    hits = [i for i,s in enumerate(lines) if ("prior_xml" in s or "can_resume" in s)]
    result["total_lines"] = len(lines)
    result["related_lines"] = [i+1 for i in hits[:40]]
    # Show only the closest code around core resume decision and loop numbering.
    ix = next((i for i in hits if "if can_resume" in lines[i]), hits[0] if hits else -1)
    if ix >= 0:
        low = max(0, ix-46)
        high = min(len(lines), ix+26)
        result["resume_code_excerpt"] = "\n".join(f"{j+1:4}: {lines[j]}" for j in range(low,high))
    result["guard_present"] = "RG_RESUME_PROTECT_PREFIX_V1" in "\n".join(lines)
    result["selector_lines"] = [
        {"line":i+1,"source":ln.strip()[:240]} for i,ln in enumerate(lines)
        if any(t in ln for t in (
            "enumerate(dialog", "enumerate(selected", "enumerate(interval",
            "enumerate(segments", "enumerate(kept", "if not can_resume",
            "output_path=prior_xml", "RG_RESUME_PROTECT_PREFIX"
        ))
    ][:25]
    return result

def manifest_summary():
    folders = [APP/"run_manifests"/"886",APP/"886"]
    result = []
    for folder in folders:
        if not folder.is_dir():
            continue
        files = sorted(
            [p for p in folder.iterdir() if p.is_file()
             and p.suffix.lower() in (".json",".log",".txt")
             and (("manifest" in p.name.lower()) or ("studio_run" in p.name.lower()) or
                  ("dialogue" in p.name.lower()) or ("resume" in p.name.lower()))],
            key=lambda p:p.stat().st_mtime,reverse=True
        )[:12]
        for p in files:
            entry = {"path":str(p),"bytes":p.stat().st_size}
            if p.suffix.lower() in (".log",".txt"):
                text = read_text(p)
                matches = [
                    ln[:280] for ln in text.splitlines()
                    if any(w in ln.lower() for w in (
                        "dialogue", "діалог", "диалог", "resume",
                        "cigarette", "готово:", "completed", "skip"
                    ))
                ]
                entry["relevant_tail"] = matches[-22:]
            elif p.stat().st_size < 2000000:
                try:
                    d=json.loads(read_text(p))
                    entry["top_keys"]=list(d)[:18] if isinstance(d,dict) else []
                    if isinstance(d,dict):
                        for key in ("dialogues","intervals","segments","items","selected","status"):
                            if key in d:
                                val=d[key]
                                entry[key] = (
                                    val[:12] if isinstance(val,list) else val
                                )
                except Exception:
                    pass
            result.append(entry)
    return result

def cigarette_audit():
    candidates = []
    for folder in (APP, APP/"886"):
        if folder.is_dir():
            for kind in ("CIGARETTE_BLUR_DETECTIONS","CIGARETTE_BLUR_QA"):
                for p in folder.glob(f"*886_5*{kind}.json"):
                    candidates.append(p)
    values=[]
    for p in candidates[:12]:
        entry={"path":str(p),"bytes":p.stat().st_size}
        try:
            d=json.loads(read_text(p))
            entry["status"]=d.get("status")
            entry["passed"]=d.get("passed")
            entry["raw"]=d.get("raw_detection_count")
            entry["tracks"]=d.get("confirmed_track_count")
            entry["intervals"]=d.get("interval_count")
            entry["overlays"]=d.get("overlay_count")
            entry["failures"]=d.get("failures")
            entry["confirmations"]=[x.get("confirmation") for x in d.get("tracks",[]) if isinstance(x,dict)][:12]
        except Exception as exc:
            entry["error"]=str(exc)[:200]
        values.append(entry)
    return values

def main():
    report={
        "schema":"RG_886_RESUME_DECISION_V1",
        "read_only":True,
        "launched_processing":False,
        "current_primary_xmls": outputs(),
        "installed_resume_source": resume_source(),
        "run_manifest": manifest_summary(),
        "cigarette_886_5_reports": cigarette_audit()
    }
    print("=== RG 886 RESUME DECISION V1 ===")
    print(json.dumps(report,ensure_ascii=False,indent=2,default=str))
if __name__=="__main__":
    main()
