#!/usr/bin/env python3
"""Read-only manifest, dialogue boundaries, and Premiere XML audit for 907."""
from __future__ import annotations
import json,sys,xml.etree.ElementTree as ET
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
ANCHORS={1:4586.25,2:5348.25,3:6737.39,4:7609.32,5:7851.75,6:7913.75,7:7979.25,8:8715.75}
def asfloat(v):
    try:return float(v)
    except (ValueError,TypeError):return None
def xml_inspect(path):
    p=Path(str(path)) if path else None
    if not p or not p.is_file():return {"exists":False,"valid":False}
    try:
        root=ET.parse(p).getroot()
        video=sum(len(x.findall("clipitem")) for x in root.findall(".//sequence/media/video/track"))
        audio=sum(len(x.findall("clipitem")) for x in root.findall(".//sequence/media/audio/track"))
        return {"exists":True,"valid":root.tag in ("xmeml","project") and video>0 and audio>0,
                "video_clips":video,"audio_clips":audio,"bytes":p.stat().st_size}
    except (OSError,ET.ParseError,ValueError) as e:return {"exists":True,"valid":False,"error":type(e).__name__}
def run():
    manifest=APP/"RG_EDITED_907_MULTI_DIALOGUE.json"
    if not manifest.is_file():
        return {"status":"MANIFEST_MISSING","manifest_path":str(manifest),"read_only":True}
    doc=json.loads(manifest.read_text(encoding="utf-8-sig"))
    if str(doc.get("stream"))!="907":raise RuntimeError("Wrong stream manifest")
    out={int(x["index"]):x for x in doc.get("outputs",[]) if isinstance(x,dict) and str(x.get("index","")).isdigit()}
    holds={int(x["index"]):x for x in doc.get("review_holds",[]) if isinstance(x,dict) and str(x.get("index","")).isdigit()}
    rows=[]
    for i in range(1,9):
        x=out.get(i) or holds.get(i) or {}
        ctx=x.get("identity_context") or {}
        ranges=x.get("selected_ranges") or []
        selected=[]
        for r in ranges:
            if not isinstance(r,dict):continue
            st=asfloat(r.get("start"));en=asfloat(r.get("end"))
            selected.append({"start":st,"end":en,"duration":round(en-st,3) if st is not None and en is not None else None})
        anchor=asfloat(ctx.get("current_anchor_sec"))
        row={"index":i,"expected_anchor":ANCHORS[i],
             "state":"OUTPUT" if i in out else "REVIEW_HOLD" if i in holds else "MISSING",
             "recorded_anchor":anchor,"anchor_delta":round(anchor-ANCHORS[i],2) if anchor is not None else None,
             "ranges":selected,"xml":xml_inspect(x.get("xml")) if i in out else None,
             "record_keys":sorted(x.keys())}
        rows.append(row)
        print("RG907|BOUNDARY_XML_ROW|"+json.dumps(row,ensure_ascii=False),flush=True)
    valid_xml=all(row["xml"] and row["xml"].get("valid") for row in rows if row["state"]=="OUTPUT")
    complete=len(out)+len(holds)==8 and set(out).isdisjoint(holds) and set(out)|set(holds)==set(range(1,9))
    return {"schema":"RG907_BOUNDARY_XML_AUDIT_V1","read_only":True,
            "xml_writes":0,"media_writes":0,"queue_writes":0,
            "manifest_status":doc.get("status"),"dialogue_count":doc.get("dialogue_count"),
            "covered_all_eight":complete,"output_indices":sorted(out),"review_indices":sorted(holds),
            "output_xml_structurally_valid":valid_xml,"boundary_release_ready":False,
            "rows":rows}
if __name__=="__main__":
    print("RG907|BOUNDARY_XML_RESULT|"+json.dumps(run(),ensure_ascii=False),flush=True)
