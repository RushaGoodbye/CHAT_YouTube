#!/usr/bin/env python3
"""Read-only operational acceptance of live RG Auto Edit Studio on AlexPC.

Never opens a stream, launches GUI, transcodes, changes queue, writes XML, or
imports side-effect-heavy production modules. This confirms on-disk readiness;
it does NOT claim GUI interaction or Premiere import testing.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
STREAMS=("886","891","892","893","899","901","902","903","904","905")
SOURCE_REQUIRED=(
    "rg_studio_ui.py",
    "rg_multi_dialogue.py",
    "rg_studio_version.py",
    "rg_studio_postrun.py",
    "rg_auto_edit_one_button.py",
)
SOURCE_OPTIONAL=(
    "rg_cigarette_blur.py",
    "rg_cigarette_detector_worker.py",
    "rg_final_release_gate.py",
)

def source_status(app=APP):
    rows=[]
    for name in SOURCE_REQUIRED+SOURCE_OPTIONAL:
        path=app/name
        row={"file":name,"required":name in SOURCE_REQUIRED,"exists":path.is_file()}
        if path.is_file():
            try:
                s=path.read_text(encoding="utf-8-sig")
                ast.parse(s,filename=name)
                row["syntax"]="PASS"
                if name=="rg_multi_dialogue.py":
                    row["selective_guard_installed"]="RG_BATCH_SELECTIVE_RETRY_V1" in s
                if name=="rg_studio_ui.py":
                    row["partial_review_ui_installed"]="RG_PARTIAL_REVIEW_UI_V1" in s
            except Exception as e:
                row["syntax"]="FAIL"
                row["error_type"]=type(e).__name__
        rows.append(row)
    ver=app/"rg_studio_version.py"
    text=ver.read_text(encoding="utf-8-sig") if ver.is_file() else ""
    match=re.search(r"\bSTUDIO_VERSION\s*=\s*['\"]([^'\"]+)['\"]",text)
    return rows, (match.group(1) if match else None)

def xml_readonly(path):
    p=Path(path)
    item={"exists":p.is_file(),"nonempty":False,"xml_parse":False,
          "video_track_clips":0,"audio_track_clips":0}
    if not p.is_file():
        return item
    item["nonempty"]=p.stat().st_size>300
    if not item["nonempty"]:
        return item
    try:
        root=ET.parse(p).getroot()
        item["xml_parse"]=root.tag in ("xmeml","project")
        for t in root.findall(".//sequence/media/video/track"):
            item["video_track_clips"]+=len(t.findall("clipitem"))
        for t in root.findall(".//sequence/media/audio/track"):
            item["audio_track_clips"]+=len(t.findall("clipitem"))
    except (OSError,ET.ParseError,ValueError) as e:
        item["parse_error_type"]=type(e).__name__
    item["structure_ok"]=bool(item["xml_parse"] and
                               item["video_track_clips"]>0 and
                               item["audio_track_clips"]>0)
    return item

def check_manifest(doc,app=APP):
    count=int(doc.get("dialogue_count") or 0)
    outputs=doc.get("outputs") or []
    holds=doc.get("review_holds") or []
    output_ids=[int(x.get("index") or 0) for x in outputs if isinstance(x,dict)]
    hold_ids=[int(x.get("index") or 0) for x in holds if isinstance(x,dict)]
    coverage=(count>0 and len(outputs)==len(output_ids)
              and len(holds)==len(hold_ids)
              and len(output_ids)==len(set(output_ids))
              and len(hold_ids)==len(set(hold_ids))
              and not (set(output_ids)&set(hold_ids))
              and set(output_ids)|set(hold_ids)==set(range(1,count+1)))
    xmls=[]
    for row in outputs:
        if not isinstance(row,dict):
            xmls.append({"structure_ok":False,"reason":"INVALID_OUTPUT_ROW"})
            continue
        x=xml_readonly(row.get("xml") or "")
        x["index"]=int(row.get("index") or 0)
        xmls.append(x)
    all_xml_ok=all(x.get("structure_ok",False) for x in xmls) if xmls else False
    safe_status=doc.get("status") in ("DIALOGUES_COMPLETE","PARTIAL_REVIEW")
    if not coverage or not safe_status or not all_xml_ok:
        state="REVIEW_OR_BROKEN"
    elif holds:
        state="PARTIAL_REVIEW"
    else:
        state="DELIVERED_XML_STRUCTURALLY_VALID"
    return {
        "state":state,"status":str(doc.get("status") or ""),
        "dialogues":count,
        "completed_xml":len(outputs),"held":len(holds),
        "completed_indices":sorted(output_ids),
        "held_indices":sorted(hold_ids),
        "unique_complete_coverage":coverage,
        "xml_all_structurally_valid":all_xml_ok,
        "xml_problems":[{"index":x.get("index"),"reason":x.get("parse_error_type") or
                           "MISSING_AUDIO_VIDEO_OR_XML"}
                        for x in xmls if not x.get("structure_ok")]
    }

def inspect(app=APP):
    sources,version=source_status(app)
    required_ok=all(r["exists"] and r.get("syntax")=="PASS"
                    for r in sources if r["required"])
    selected=next((x for x in sources if x["file"]=="rg_multi_dialogue.py"),{})
    patches_ok=bool(selected.get("selective_guard_installed"))
    streams={}
    for stream in STREAMS:
        file=app/("RG_EDITED_"+stream+"_MULTI_DIALOGUE.json")
        if not file.is_file():
            streams[stream]={"state":"MANIFEST_UNAVAILABLE"}
            continue
        try:
            doc=json.loads(file.read_text(encoding="utf-8-sig"))
            if str(doc.get("stream"))!=stream:
                streams[stream]={"state":"WRONG_STREAM_IN_MANIFEST"}
            else:
                streams[stream]=check_manifest(doc,app)
        except (ValueError,TypeError,OSError) as e:
            streams[stream]={"state":"MANIFEST_INVALID","error_type":type(e).__name__}
    return {
        "schema":"RG_AUTO_EDIT_OPERATIONAL_ACCEPTANCE_V1",
        "read_only":True,
        "program_launch_attempted":False,
        "gui_responsiveness_tested":False,
        "premiere_import_tested":False,
        "stream_processing_started":False,
        "media_writes":0,"xml_writes":0,"queue_writes":0,
        "app_exists":app.is_dir(),
        "studio_version":version,
        "required_source_syntax_pass":required_ok,
        "selective_retry_patch_present":patches_ok,
        "source_modules":sources,
        "stream_manifests":streams,
        "operational_gate":"BACKEND_SOURCE_PASS_PENDING_GUI_SMOKE" if
             required_ok and patches_ok else "BACKEND_SOURCE_NOT_VERIFIED",
    }

if __name__=="__main__":
    report=inspect()
    print("RG_STUDIO_OPERATIONAL_ACCEPTANCE|"+
          json.dumps(report,ensure_ascii=False,sort_keys=True),flush=True)
    if report["operational_gate"]!="BACKEND_SOURCE_PASS_PENDING_GUI_SMOKE":
        sys.exit(2)
