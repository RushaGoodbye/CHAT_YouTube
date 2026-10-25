#!/usr/bin/env python3
"""Read only the installed Studio UI queue/QA status code near target methods."""
from __future__ import annotations
import json
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
TARGETS={
    "rg_studio_ui.py":(
        "def _batch_refresh","def _batch_set","def _batch_next",
        "def _batch_finished","def _batch_finish",
        "def recheck_existing_qa","PARTIAL_REVIEW",
        "RGPOSTRUN", "QProcess", "def _load_batch_ui_state",
        "def _save_batch_ui_state"),
    "rg_studio_postrun.py":("def main(","def _primary_outputs","PARTIAL_REVIEW"),
}
def extract(filename,patterns):
    file=APP/filename
    if not file.is_file():return {"missing":True}
    rows=file.read_text(encoding="utf-8-sig",errors="replace").splitlines()
    matched={}
    for pattern in patterns:
        hits=[i for i,line in enumerate(rows) if pattern.lower() in line.lower()]
        excerpts=[]
        for index in hits[:6]:
            a=max(0,index-7);b=min(len(rows),index+29)
            excerpts.append({"line":index+1,"text":"\n".join(f"{n+1}: {rows[n]}" for n in range(a,b))})
        matched[pattern]={"hits":len(hits),"excerpts":excerpts}
    return {"lines":len(rows),"patterns":matched}

if __name__=="__main__":
    result={"schema":"RG_AUTO_EDIT_UI_STATUS_SOURCE_AUDIT_V1","read_only":True,
            "source_writes":0,"media_writes":0,
            "files":{filename:extract(filename,patterns) for filename,patterns in TARGETS.items()}}
    print("RG_PARTIAL_UI_AUDIT|"+json.dumps(result,ensure_ascii=False),flush=True)
