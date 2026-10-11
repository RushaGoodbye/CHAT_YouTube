#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RG 904 postrun QA failure read-only forensic. NO writes, execution of backend, or edits."""
from __future__ import annotations
import json
import re
from pathlib import Path
import os
import time
import xml.etree.ElementTree as ET

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
STREAM="904"
OUTPUT=APP/STREAM
def json_file(p):
    try:return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:return {"read_error":str(e)[:220]}

def summarize_item(p):
    return {"name":p.name,"bytes":p.stat().st_size,"mtime":round(p.stat().st_mtime,1)}

def candidates(folder):
    terms=("CIGARETTE","SMOKING","BLUR","QA","MULTI","904")
    xs=[]
    if not folder.is_dir():return {"missing":True}
    for p in folder.iterdir():
        if p.is_file() and any(t in p.name.upper() for t in terms) and (
            "904" in p.name or p.name.upper().startswith("RG_POSTRUN")
        ): xs.append(summarize_item(p))
    return sorted(xs,key=lambda x:x["name"])[:250]

def inspect_xml(p):
    if not p.is_file():return {"file":p.name,"missing":True}
    try:
        tree=ET.parse(p)
        seq=tree.getroot().find("sequence")
        if seq is None:raise ValueError("no sequence")
        markers=[{"name":m.findtext("name"),"in":m.findtext("in"),"out":m.findtext("out")}
            for m in seq.findall("marker")]
        smoke=[m for m in markers if ("КУРІННЯ" in (m["name"] or "") or "SMOK" in (m["name"] or "").upper())]
        clipitems=len(seq.findall(".//video/track/clipitem"))
        filters=len(seq.findall(".//video/track/clipitem/filter"))
        return {"file":p.name,"bytes":p.stat().st_size,"marker_count":len(markers),
            "smoking_marker_count":len(smoke),"smoking_markers":smoke[:12],
            "marker_sample":markers[:7],"video_clip_count":clipitems,"video_clip_filters":filters}
    except Exception as e:
        return {"file":p.name,"error":str(e)[:300]}

def code_fragments(p, terms, max_rows=32):
    if not p.is_file():return {"missing":True}
    rows=p.read_text(encoding="utf-8-sig",errors="replace").splitlines()
    matches=[]
    for i,line in enumerate(rows):
        if any(re.search(q,line,re.I) for q in terms):
            matches.append({"line":i+1,"snippet":"\n".join(
                f"{j+1}: {rows[j]}" for j in range(max(0,i-3),min(len(rows),i+12)))})
            if len(matches)>=max_rows:break
    return {"file":p.name,"matches":matches}

def main():
    manifest=json_file(APP/"RG_EDITED_904_MULTI_DIALOGUE.json")
    qa=json_file(OUTPUT/"RG_POSTRUN_QA.json")
    skips=manifest.get("skipped_screenshots") or []
    main_xml=[OUTPUT/f"RG_EDITED_904_{i}.xml" for i in (1,2,3,4,5,6,7)]
    indexes=[]
    for e in manifest.get("outputs") or []:
        indexes.append({"index":e.get("index"),"screenshot":e.get("screenshot"),
                        "xml":Path(e.get("xml","")).name,"has_job_key":bool(e.get("job_key"))})
    top={"schema":"RG_904_FINAL_QA_READONLY_DIAG_V1","timestamp":time.time(),
      "manifest":{"status":manifest.get("status"),"dialogue_count":manifest.get("dialogue_count"),
                  "completed_dialogues":manifest.get("completed_dialogues"),
                  "failed_dialogue":manifest.get("failed_dialogue"),
                  "skipped_screenshots":skips,"outputs":indexes},
      "postrun":{"passed":qa.get("passed"),"dialogues":qa.get("dialogues"),
                 "xml_count":qa.get("xml_count"),
                 "checks":[{"name":c.get("name"),"ok":c.get("ok"),"detail":str(c.get("detail"))[:1200]} for c in qa.get("checks",[])]},
      "inventory_root":candidates(APP),"inventory_904":candidates(OUTPUT),
      "xml_inspect":[inspect_xml(x) for x in main_xml if x.is_file()],
      "postrun_code":code_fragments(APP/"rg_studio_postrun.py",
         ["Повнота діалогів","CIGARETTE_BLUR_QA","Блюр сигарети","Сигарети","MISSING PRIMARY",
           "skipped_screenshots","expected.*xml"],max_rows=34),
      "backend_code":code_fragments(APP/"rg_auto_edit_one_button.py",
         ["CIGARETTE_BLUR_QA","CIGARETTE_BLUR_DETECTIONS","RG_SMOKING_TIMELINE_MARKERS_IMPORT_R1",
          "RG_SMOKING_UNCERTAIN_TIMELINE_HOTFIX_R1"],max_rows=16),
      "production_files_modified":False}
    print("RG_904_FINAL_QA_READONLY_DIAG")
    print(json.dumps(top,ensure_ascii=False,indent=2,default=str))
if __name__=="__main__":main()
