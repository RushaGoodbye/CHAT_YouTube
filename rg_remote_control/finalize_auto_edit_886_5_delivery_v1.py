#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finish 886_5 delivery without rerunning any dialogue. Fail-closed."""
from __future__ import annotations
import datetime, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time
import xml.etree.ElementTree as ET

APP=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=APP/"RG_EDITED_886_5.xml"
DEST=APP/"886"/ROOT.name
DETECT=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
QA=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_QA.json"
BACKUP=DATA/"release_backups"/"PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648"
CONFIG=APP/"rg_auto_edit_config.json"
VERSION="RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2"
def log(label,value=None):
    print(label,flush=True)
    if value is not None:
        print(json.dumps(value,ensure_ascii=False,indent=2,default=str),flush=True)
def jload(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for buf in iter(lambda:stream.read(1024*1024),b""):
            h.update(buf)
    return h.hexdigest()
def norm(node):
    if node is None:return None
    return (node.tag,tuple(sorted(node.attrib.items())),(node.text or "").strip(),tuple(norm(c) for c in node))
def xroot(p):
    r=ET.parse(p).getroot()
    if r.tag!="xmeml" or r.find("sequence") is None:
        raise RuntimeError(f"Invalid Premiere XML: {p}")
    return r
def active_guard():
    command=r"""$p=Get-CimInstance Win32_Process | Where-Object {
 (($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and
 (($_.CommandLine -like '*rg_production_wrapper.py*') -or
  ($_.CommandLine -like '*rg_multi_dialogue.py*') -or
  ($_.CommandLine -like '*rg_auto_edit_one_button.py*'))
};$p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress
"""
    p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",command],
      capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
    if p.returncode:
        raise RuntimeError("Cannot verify that processing is stopped: "+p.stderr[-900:])
    if p.stdout.strip() not in ("","null","[]"):
        raise RuntimeError("Processing active; delivery blocked: "+p.stdout[-900:])
def xml_integrity():
    before=xroot(BACKUP/ROOT.name)
    after=xroot(ROOT)
    pre_audio=before.find("./sequence/media/audio")
    post_audio=after.find("./sequence/media/audio")
    if pre_audio is None or norm(pre_audio)!=norm(post_audio):
        raise RuntimeError("Existing audio track changed - FAIL")
    pre_video=before.findall("./sequence/media/video/track")
    post_video=after.findall("./sequence/media/video/track")
    if not pre_video or len(post_video)!=len(pre_video)+1:
        raise RuntimeError("Unexpected video track count - FAIL")
    for x,y in zip(pre_video,post_video):
        if norm(x)!=norm(y):raise RuntimeError("Existing video changed - FAIL")
    cig=post_video[-1].findall("./clipitem")
    if len(cig)!=3:
        raise RuntimeError(f"Expected exactly 3 cigarette blur overlays, got {len(cig)}")
    clips=[]
    for c in cig:
        if not str(c.get("id") or "").startswith("rg-cigarette-"):
            raise RuntimeError("Unexpected video overlay in blur track")
        effects=[f.find("effect") for f in c.findall("filter")]
        eids=[ef.findtext("effectid") for ef in effects if ef is not None]
        if "Gaussian Blur" not in eids or "crop" not in eids:
            raise RuntimeError("Missing Gaussian Blur or Crop in local overlay")
        crops=[e for e in effects if e is not None and e.findtext("effectid")=="crop"]
        if len(crops)!=1:raise RuntimeError("Crop count mismatch")
        coords={}
        for p in crops[0].findall("parameter"):
            coords[p.findtext("parameterid")]=float(p.findtext("value") or 0)
        if set(coords)!={"left","right","top","bottom"}:
            raise RuntimeError("Incomplete Crop parameters")
        if any(not 0<=v<=100 for v in coords.values()):
            raise RuntimeError("Invalid Crop parameter outside [0..100]")
        if not (coords["left"]+coords["right"]>30 and coords["top"]+coords["bottom"]>30):
            raise RuntimeError("Whole-frame or excessive area blur forbidden")
        st=int(float(c.findtext("start") or 0));ed=int(float(c.findtext("end") or 0))
        if ed<=st:raise RuntimeError("Overlay duration invalid")
        clips.append({"id":c.get("id"),"crop_pct":coords,"frames":ed-st})
    return {"audio_unchanged":True,"original_video_unchanged":True,
            "localized_overlay_count":len(clips),"overlay_samples":clips}
def audit_expected():
    logs=[APP/"run_manifests"/"886"/"STUDIO_RUN.log"]
    totals=[]
    for logpath in logs:
        if logpath.is_file():
            tail=logpath.read_text(encoding="utf-8-sig",errors="replace")[-350000:]
            totals.extend([int(x) for x in re.findall(r"\[DIALOGUE\s+\d+/(\d+)\]",tail)])
    total=max(totals) if totals else None
    names={}
    for p in list(APP.glob("RG_EDITED_886_[0-9]*.xml"))+list((APP/"886").glob("RG_EDITED_886_[0-9]*.xml")):
        m=re.fullmatch(r"RG_EDITED_886_(\d+)\.xml",p.name,re.I)
        if m:names.setdefault(int(m.group(1)),[]).append(str(p))
    return {"expected_dialogue_jobs_from_latest_log":total,
            "current_primary_numbers":sorted(names),
            "current_primary_count":len(names),
            "complete_by_count":(total is not None and len(names)>=total)}
def main():
    log("=== 886_5 DELIVERY AND STREAM QA PREFLIGHT ===")
    active_guard()
    for p in (ROOT,DETECT,QA,CONFIG,BACKUP/ROOT.name):
        if not p.is_file():raise RuntimeError("Required verified artifact missing: "+str(p))
    conf=jload(CONFIG).get("cigarette_blur") or {}
    if conf.get("version")!=VERSION or not all(conf.get(k) is True for k in ("mandatory","fail_closed","whole_frame_blur_forbidden")):
        raise RuntimeError("Mandatory cigarette blur safety configuration mismatch")
    d=jload(DETECT);q=jload(QA)
    if not (d.get("passed") is True and d.get("version")==VERSION and d.get("status")=="TRACKED"):
        raise RuntimeError("Detection report not confirmed")
    if int(d.get("raw_detection_count") or 0)!=2 or int(d.get("confirmed_track_count") or 0)!=1:
        raise RuntimeError("Unexpected detection count")
    if not any(t.get("confirmation")=="SHORT_STABLE" for t in d.get("tracks") or []):
        raise RuntimeError("SHORT_STABLE track not confirmed")
    if int(d.get("interval_count") or 0)!=3:
        raise RuntimeError("Expected exactly 3 local blur intervals")
    if not (q.get("passed") is True and q.get("policy")=="MANDATORY_TRACKED_OBJECT_ONLY_CROP_GAUSSIAN_BLUR"):
        raise RuntimeError("Cigarette blur QA failed")
    if int(q.get("overlay_count") or 0)!=3 or int(q.get("expected_overlay_count") or 0)!=3:
        raise RuntimeError("Overlay coverage count mismatch")
    cov=q.get("coverage_qa") or {}
    if cov.get("passed") is not True:
        raise RuntimeError("Blur coverage QA failed")
    integrity=xml_integrity()
    orig_hash=sha(ROOT)
    python_dir=str(APP)
    if python_dir not in sys.path:sys.path.insert(0,python_dir)
    from VALIDATE_PREMIERE_XML import validate
    val=validate(ROOT)
    if isinstance(val,dict) and val.get("passed") is False:
        raise RuntimeError("Premiere validator returned FAIL")
    from rg_production_stability import acquire_stream_lock,release_stream_lock
    lock=acquire_stream_lock("886",owner_pid=os.getpid(),owner="RG Auto Edit 886_5 delivery QA")
    published=False
    previous_8862=[]
    try:
        active_guard()
        for p in (APP/"RG_EDITED_886_2.xml",APP/"886"/"RG_EDITED_886_2.xml"):
            if p.is_file():previous_8862.append((p,sha(p)))
        if DEST.is_file() and sha(DEST)!=orig_hash:
            raise RuntimeError("Delivery 886_5 already exists and differs; auto-overwrite forbidden")
        if not DEST.is_file():
            DEST.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="._RG_EDITED_886_5_",suffix=".xml",
                       dir=str(DEST.parent),delete=False) as temp:
                scratch=pathlib.Path(temp.name)
            try:
                shutil.copy2(ROOT,scratch)
                if sha(scratch)!=orig_hash:
                    raise RuntimeError("Staged XML differs from verified 886_5")
                active_guard()
                if sha(ROOT)!=orig_hash:
                    raise RuntimeError("Original 886_5 XML changed during delivery")
                os.replace(scratch,DEST)
                published=True
            finally:
                if scratch.exists():scratch.unlink()
        if sha(DEST)!=orig_hash:
            raise RuntimeError("Delivered XML SHA mismatch")
        if any(sha(p)!=digest for p,digest in previous_8862):
            raise RuntimeError("886_2 XML was changed - delivery invalid")
        result={
          "status":"PASS",
          "scope":"886_5_DELIVERY_AND_QA",
          "delivery_action":"COPIED" if published else "ALREADY_IDENTICAL",
          "source":str(ROOT),"destination":str(DEST),"sha256":orig_hash,
          "premiere_validator":"PASS","cigarette_qa":"PASS",
          "detection_confirmation":"SHORT_STABLE","cigarette_overlays":3,
          "safety_flags":{"mandatory":True,"fail_closed":True,"whole_frame_blur_forbidden":True},
          "checks":integrity,
          "dialogue_886_2_unchanged":True,
          "stream_inventory":audit_expected(),
          "full_stream_postrun_qa":"NOT_RUN",
          "full_stream_finished":False,
        }
        if result["stream_inventory"]["complete_by_count"]:
            result["next_action"]="RUN_FULL_STREAM_POSTRUN_QA_ONLY"
        else:
            result["next_action"]="VERIFY_REMAINING_DIALOGUE_JOB_BEFORE_POSTRUN"
        log("=== 886_5 DELIVERY AND STREAM QA RESULT ===",result)
    finally:
        release_stream_lock("886",str((lock or {}).get("run_id") or ""))

if __name__=="__main__":
    try:main()
    except Exception as exc:
        log("=== 886_5 DELIVERY AND STREAM QA STOPPED ===",{"status":"STOPPED","reason":str(exc)})
        raise SystemExit(2)
