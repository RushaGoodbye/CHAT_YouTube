#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""886_5 only: revalidate saved raw detections, stage tracked localized blur, verify, publish.

Does not run stream/dialogue processing, alter other XMLs, or change audio.
Stops fail-closed on any ambiguity. Originals are backed up before publication.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
XML=APP/"RG_EDITED_886_5.xml"
DET=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
QA=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_QA.json"
CONFIG=APP/"rg_auto_edit_config.json"
EXPECTED_VERSION="RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2"

def log(label,obj=None):
    print(label,flush=True)
    if obj is not None:print(json.dumps(obj,ensure_ascii=False,indent=2,default=str),flush=True)

def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def put_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def reject_active_processes():
    ps=r"""$p=Get-CimInstance Win32_Process | Where-Object {
  (($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and
  (($_.CommandLine -like '*rg_production_wrapper.py*') -or
   ($_.CommandLine -like '*rg_multi_dialogue.py*') -or
   ($_.CommandLine -like '*rg_auto_edit_one_button.py*'))
}
$p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress
"""
    ret=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],
                       capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
    if ret.returncode!=0:
        raise RuntimeError("Cannot confirm idle production backend: "+ret.stderr[-1500:])
    stdout=ret.stdout.strip()
    if stdout not in ("","null","[]"):
        raise RuntimeError("Production running - repair refused: "+stdout[:1200])

def normalized_node(node):
    if node is None:return None
    return (node.tag,tuple(sorted(node.attrib.items())),
            (node.text or "").strip(),tuple(normalized_node(c) for c in node))

def xml_root(path):
    r=ET.parse(path).getroot()
    if r.tag!="xmeml" or r.find("sequence") is None:
        raise RuntimeError("Invalid Premiere xmeml XML: "+str(path))
    return r

def original_signature(path):
    root=xml_root(path)
    audio=root.find("./sequence/media/audio")
    video=root.find("./sequence/media/video")
    if audio is None or video is None:
        raise RuntimeError("Existing XML missing source audio or video")
    primary=video.findall("track")
    if not primary:raise RuntimeError("Existing XML video track missing")
    old_cig=[x for x in root.findall(".//clipitem") if (x.get("id") or "").startswith("rg-cigarette-")]
    if old_cig:raise RuntimeError("Cigarette blur already exists; refuse to overwrite existing blur")
    return {"audio":normalized_node(audio),
            "video_tracks":[normalized_node(x) for x in primary],
            "original_video_track_count":len(primary),
            "old_clips":len(root.findall(".//clipitem"))}

def validate_staged(original,staged,qa,lib):
    a=original_signature(original)
    b=xml_root(staged)
    assert b.find("./sequence/media/audio") is not None
    if normalized_node(b.find("./sequence/media/audio"))!=a["audio"]:
        raise RuntimeError("Audio track modified - refused")
    new_tracks=b.findall("./sequence/media/video/track")
    if len(new_tracks)!=a["original_video_track_count"]+1:
        raise RuntimeError("Unexpected video track modifications")
    if [normalized_node(x) for x in new_tracks[:a["original_video_track_count"]]]!=a["video_tracks"]:
        raise RuntimeError("Original video clips or effects changed - refused")
    if qa.get("passed") is not True:
        raise RuntimeError("Cigarette overlay QA returned FAIL: "+json.dumps(qa.get("failures"),ensure_ascii=False))
    count=int(qa.get("overlay_count") or 0)
    if count<=0 or count!=int(qa.get("expected_overlay_count") or 0):
        raise RuntimeError("Cigarette overlays missing or count mismatch")
    if qa.get("policy")!="MANDATORY_TRACKED_OBJECT_ONLY_CROP_GAUSSIAN_BLUR":
        raise RuntimeError("Only-localized cigarette blur policy missing")
    structural=lib.verify_cigarette_blur(staged,expected_count=count)
    if not structural.get("passed"):
        raise RuntimeError("Structural blur verification failed: "+repr(structural))
    # The installed Premiere validator is mandatory for publication.
    sys.path.insert(0,str(APP))
    from VALIDATE_PREMIERE_XML import validate
    result=validate(staged)
    if isinstance(result,dict) and result.get("passed") is False:
        raise RuntimeError("Premiere validation result indicates failure: "+repr(result)[:2000])
    return {"audio_identical":True,
            "original_video_tracks_identical":True,
            "new_video_tracks":1,
            "premiere_validator":"PASS",
            "verified_overlay_count":count,
            "original_clip_count":a["old_clips"]}

def main():
    log("=== 886_5 CIGARETTE LOCAL XML REPAIR PREFLIGHT ===")
    reject_active_processes()
    sys.path.insert(0,str(APP))
    from rg_production_stability import acquire_stream_lock,release_stream_lock
    lock=acquire_stream_lock("886",owner_pid=os.getpid(),owner="RG cigarette XML repair 886_5")
    try:
        for item in (XML,DET,CONFIG,APP/"rg_cigarette_blur.py",APP/"VALIDATE_PREMIERE_XML.py"):
            if not item.is_file():
                raise RuntimeError("Required file missing: "+str(item))
        config=load_json(CONFIG)
        opts=dict(config.get("cigarette_blur") or {})
        if opts.get("version")!=EXPECTED_VERSION:
            raise RuntimeError("Installed cigarette engine version mismatch")
        if not all(opts.get(k) is True for k in ("mandatory","fail_closed","whole_frame_blur_forbidden")):
            raise RuntimeError("Mandatory localized blur policy not active")
        old=load_json(DET)
        if old.get("status")!="AMBIGUOUS" or old.get("passed") is not False:
            raise RuntimeError("Detection report is not the known pre-hotfix ambiguous result; refuse mutation")
        if int(old.get("raw_detection_count") or 0)!=2:
            raise RuntimeError("Unexpected raw detection count; refuse mutation")
        rejected=old.get("rejected_tracks") or []
        if len(rejected)!=1 or len(rejected[0].get("hits") or [])!=2:
            raise RuntimeError("Rejected detection evidence differs from verified two-hit 886_5 case")
        if old.get("tracks") or old.get("intervals"):
            raise RuntimeError("Existing confirmed detections found: refuse reclassification")
        import rg_cigarette_blur as lib
        if getattr(lib,"VERSION",None)!=EXPECTED_VERSION:
            raise RuntimeError("Live cigarette module version mismatch")
        track=copy.deepcopy(rejected[0])
        hits=track["hits"]
        scores=[float(h.get("score") or 0.0) for h in hits]
        classes=[str(h.get("class") or "") for h in hits]
        if classes!=["smoking cigarette","smoking cigarette"]:
            raise RuntimeError("Unexpected detection class; must inspect manually")
        if not all(0.08 <= x < 0.34 for x in scores):
            raise RuntimeError("Detection scores differ from verified short stable evidence")
        first=min(float(h["t"]) for h in hits)
        last=max(float(h["t"]) for h in hits)
        if not (0.05 <= last-first <= 0.08 and 9500 < first < 9700):
            raise RuntimeError("Detection timestamps differ from verified 886_5 case")
        if any(len(h.get("bbox") or [])!=4 for h in hits):
            raise RuntimeError("Invalid cigarette bounding boxes")
        accepted,rejected_now=lib._confirm_tracks([track],opts,[(first-2.0,last+2.0)])
        if len(accepted)!=1 or rejected_now or accepted[0].get("confirmation")!="SHORT_STABLE":
            raise RuntimeError("SHORT_STABLE validation did not pass; refusing unblurred delivery")
        intervals=accepted[0].get("intervals") or []
        if not intervals:raise RuntimeError("No tracked motion intervals available")
        updated=copy.deepcopy(old)
        updated.update({
            "version":EXPECTED_VERSION,
            "passed":True,"status":"TRACKED",
            "tracks":accepted,"rejected_tracks":[],
            "confirmed_track_count":1,"rejected_track_count":0,
            "unconfirmed_detection_count":0,
            "intervals":intervals,"interval_count":len(intervals),
            "failures":[],
            "evidence_source":"EXISTING_RAW_DETECTION_REPORT_REVALIDATED_WITH_SHORT_STABLE_V2",
            "original_detection_report_sha256":sha256(DET),
        })
        sig=original_signature(XML)
        if not sig["audio"] or not sig["video_tracks"]:
            raise RuntimeError("Base XML lacks expected tracks")
        ts=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup=DATA/"release_backups"/("PRE_886_5_CIGARETTE_XML_REPAIR_"+ts)
        backup.mkdir(parents=True,exist_ok=False)
        originals=[XML,DET]+([QA] if QA.is_file() else [])
        proofs={}
        for f in originals:
            dst=backup/f.name
            shutil.copy2(f,dst)
            proofs[f.name]=sha256(f)
            if sha256(dst)!=proofs[f.name]:
                raise RuntimeError("Backup SHA256 mismatch: "+f.name)
        put_json(backup/"BACKUP_PROOFS.json",{"created_at":ts,"sha256":proofs,
            "config_version":EXPECTED_VERSION,"scope":"886_5_only",
            "rollback":"Copy backed-up XML and detection JSON back to F: app folder if publication QA fails"})
        log("ORIGINAL FILES BACKED UP",{"folder":str(backup),"files":list(proofs)})
        with tempfile.TemporaryDirectory(prefix="rg_8865_cigarette_",dir=str(APP)) as td:
            stage=Path(td)
            staged=stage/XML.name
            shutil.copy2(XML,staged)
            qa=lib.inject_cigarette_blur(staged,updated,opts,fps=30)
            validation=validate_staged(XML,staged,qa,lib)
            put_json(stage/DET.name,updated)
            put_json(stage/QA.name,qa)
            # Never publish if production was launched while checking.
            reject_active_processes()
            if any(sha256(f)!=digest for f,digest in ((p,proofs[p.name]) for p in originals)):
                raise RuntimeError("Original files changed concurrently; refusing publication")
            # Same-directory replacements avoid partial XML writes.
            os.replace(staged,XML)
            try:
                os.replace(stage/DET.name,DET)
                os.replace(stage/QA.name,QA)
            except Exception:
                # Restore the pre-repair state on any sidecar failure.
                shutil.copy2(backup/XML.name,XML)
                shutil.copy2(backup/DET.name,DET)
                if (backup/QA.name).is_file():
                    shutil.copy2(backup/QA.name,QA)
                else:
                    try:QA.unlink()
                    except FileNotFoundError:pass
                raise
        final=lib.verify_cigarette_blur(XML,expected_count=int(qa["overlay_count"]))
        if not final.get("passed"):
            shutil.copy2(backup/XML.name,XML)
            shutil.copy2(backup/DET.name,DET)
            if (backup/QA.name).is_file():
                shutil.copy2(backup/QA.name,QA)
            else:
                try:QA.unlink()
                except FileNotFoundError:pass
            raise RuntimeError("Post-publication blur verification failed - original artifacts restored from "+str(backup))
        report={
            "status":"PASS",
            "scope":"886_5_XML_ONLY",
            "stream_reprocessed":False,
            "detector_rerun":False,
            "raw_evidence_count":2,
            "confirmation":accepted[0]["confirmation"],
            "confirmed_tracks":1,
            "localized_intervals":len(intervals),
            "blur_overlays":int(qa["overlay_count"]),
            "coverage_qa_pass":bool((qa.get("coverage_qa") or {}).get("passed")),
            "mandatory":True,"fail_closed":True,"whole_frame_blur_forbidden":True,
            "audio_unchanged":validation["audio_identical"],
            "existing_video_unchanged":validation["original_video_tracks_identical"],
            "premiere_xml_valid":validation["premiere_validator"],
            "xml":str(XML),"detector_report":str(DET),"qa_report":str(QA),"backup":str(backup),
            "whole_stream_postrun_qa":"NOT_RUN",
        }
        log("=== 886_5 CIGARETTE LOCAL XML REPAIR RESULT ===",report)

    finally:
        release_stream_lock("886",str((lock or {}).get("run_id") or ""))

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        log("=== 886_5 CIGARETTE LOCAL XML REPAIR STOPPED ===",
            {"status":"STOPPED","reason":str(exc)})
        raise SystemExit(2)
