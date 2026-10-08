#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RG Auto Edit 886_5: audited microphone false-positive quarantine.

Restores the exact clean pre-cigarette XML, and removes ONLY the previous
three cigarette overlays by restoring a byte-for-byte verified pre-repair copy.
WITHHOLDS the formerly published copy. It explicitly invalidates semantic
cigarette PASS sidecars. Full dialogue cigarette QA is STILL REQUIRED.

No stream rerun. No original media touched. No modifications of 886_2.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
PRIMARY=APP/"RG_EDITED_886_5.xml"
DELIVERED=APP/"886"/"RG_EDITED_886_5.xml"
DETECT=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
QA=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_QA.json"
CONFIG=APP/"rg_auto_edit_config.json"
HOLD=APP/"886"/"RG_EDITED_886_5.SEMANTIC_HOLD.json"
ROOT_HOLD=APP/"RG_EDITED_886_5.SEMANTIC_HOLD.json"
PRIOR=DATA/"release_backups"/"PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648"
REPORT_ROOT=DATA/"oss_shadow"
EXPECTED_BLURRED_SHA="32a47526e49507299db894bfb7300a7255074cd8881a3115c1f8a4bbc9569963"
EXPECTED_BLUR_VERSION="RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2"
SCHEMA="RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1"
ERROR="SEMANTIC_FALSE_POSITIVE_MICROPHONE_LOGO"
REVIEWED_INTERVAL=[9558.897,9561.20]
MODIFIED_ARTIFACTS=(PRIMARY,DELIVERED,DETECT,QA)
BLUR_IDS=("rg-cigarette-1","rg-cigarette-2","rg-cigarette-3")

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for x in iter(lambda:f.read(1024*1024),b""):h.update(x)
    return h.hexdigest()

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def save_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def norm(node):
    if node is None:return None
    return (node.tag,tuple(sorted(node.attrib.items())),
            (node.text or "").strip(),tuple(norm(ch) for ch in node))

def check_xml_xml(primary_bytes,original_bytes):
    """The only allowed delta: one trailing video track containing 3 localized overlays."""
    x=ET.fromstring(primary_bytes); base=ET.fromstring(original_bytes)
    if x.tag!="xmeml" or base.tag!="xmeml":raise RuntimeError("Not a Premiere xmeml XML")
    xseq=x.find("sequence"); bseq=base.find("sequence")
    if xseq is None or bseq is None:raise RuntimeError("Missing Premiere sequence")
    xa=x.find("./sequence/media/audio");ba=base.find("./sequence/media/audio")
    if xa is None or ba is None or norm(xa)!=norm(ba):
        raise RuntimeError("Audio subtree changed - no repair permitted")
    xv=x.find("./sequence/media/video");bv=base.find("./sequence/media/video")
    if xv is None or bv is None:raise RuntimeError("Missing video tracks")
    xp=xv.findall("track");bp=bv.findall("track")
    if not bp or len(xp)!=len(bp)+1:
        raise RuntimeError("Expected clean original video plus exactly one blur track")
    if [norm(k) for k in xp[:-1]]!=[norm(k) for k in bp]:
        raise RuntimeError("Non-cigarette video tracks differ from clean backup")
    overlay=xp[-1]
    # Exactly the 3 previously reviewed overlays. Other or malformed effects block edits.
    clips=overlay.findall("clipitem")
    ids=[c.get("id") for c in clips]
    if len(clips)!=3 or set(ids)!=set(BLUR_IDS):
        raise RuntimeError("Unexpected overlay count or IDs: "+repr(ids))
    # Premiere track may contain harmless <enabled>/<locked> metadata.
    # Exact full-document comparison after removing the track below is the
    # stronger guard against *any* non-cigarette source edits.
    details=[]
    for c in clips:
        effects=[e.find("effect") for e in c.findall("filter")]
        kinds=[e.findtext("effectid") for e in effects if e is not None]
        # Premiere overlay clips can contain additional effects/parameters,
        # e.g. motion/opacity. Earlier delivery QA only required both blur
        # and crop. The stricter "exactly 2 effects" assumption incorrectly
        # blocked the real 886_5 XML. We are restoring the *entire* clean
        # pre-blur XML, not selectively stripping a filter from a clip.
        # Full-document structural equality after removal of this known
        # trailing track (below), plus the known exact SHA256 of both active
        # XML copies, is the stronger verification of what will be restored.
        if kinds.count("Gaussian Blur")!=1 or kinds.count("crop")!=1:
            raise RuntimeError("Missing/duplicate Gaussian Blur or crop in "+
                repr(c.get("id"))+": "+repr(kinds))
        if any(k is None for k in kinds):
            raise RuntimeError("Overlay contains filter with no effectid: "+repr(c.get("id")))
        if int(float(c.findtext("end") or 0))<=int(float(c.findtext("start") or 0)):
            raise RuntimeError("Overlay has invalid timeline boundaries")
        coords={}
        crop=next(f for f in effects if f is not None and f.findtext("effectid")=="crop")
        for p in crop.findall("parameter"):
            coords[p.findtext("parameterid")]=float(p.findtext("value") or 0)
        if set(coords)!={"left","right","top","bottom"}:
            raise RuntimeError("Unexpected crop coordinates")
        if any(not 0<=v<=100 for v in coords.values()):
            raise RuntimeError("Crop out of range")
        if coords["left"]+coords["right"]<=30 or coords["top"]+coords["bottom"]<=30:
            raise RuntimeError("Whole-frame blur detected; cannot use this local recovery")
        details.append({"id":c.get("id"),"start":c.findtext("start"),"end":c.findtext("end"),
                        "crop_pct":coords,"effect_ids":kinds})
    # This must hold over the WHOLE XML, not just video and audio.
    xv.remove(overlay)
    if norm(x)!=norm(base):
        raise RuntimeError("XML contains changes other than the 3 overlays: restore blocked")
    return {"semantic_xml_equal_after_overlay_removal":True,
            "audio_identical":True,"original_video_tracks_identical":True,
            "removed_blur_overlays":3,"overlay_details":details}

def check_process_idle():
    ps=r"""$ErrorActionPreference='Stop'
$p=Get-CimInstance Win32_Process | Where-Object {
 ($_.Name -match '^pythonw?\.exe$') -and (
  $_.CommandLine -like '*rg_production_wrapper.py*' -or
  $_.CommandLine -like '*rg_multi_dialogue.py*' -or
  $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
$p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress
"""
    r=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],
        capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
    if r.returncode!=0 or r.stdout.strip() not in ("","null","[]"):
        raise RuntimeError("Active processing or uncertain process state; quarantine refused")

def preflight():
    check_process_idle()
    for p in (PRIMARY,DELIVERED,DETECT,QA,CONFIG,PRIOR/PRIMARY.name,PRIOR/DETECT.name):
        if not p.is_file():raise RuntimeError("Required artifact missing: "+str(p))
    cfg=read_json(CONFIG).get("cigarette_blur") or {}
    if cfg.get("version")!=EXPECTED_BLUR_VERSION or not all(cfg.get(k) is True for k in (
            "mandatory","fail_closed","whole_frame_blur_forbidden")):
        raise RuntimeError("Mandatory cigarette policy changed")
    if sha(PRIMARY)!=EXPECTED_BLURRED_SHA or sha(DELIVERED)!=EXPECTED_BLURRED_SHA:
        raise RuntimeError("Previously validated 886_5 XML changed; refusing stale mutation")
    original_bytes=(PRIOR/PRIMARY.name).read_bytes()
    current=PRIMARY.read_bytes()
    # Verify original clean XML really was captured BEFORE the microphone blur.
    audit=check_xml_xml(current,original_bytes)
    if DELIVERED.read_bytes()!=current:
        raise RuntimeError("Delivered copy differs from primary")
    det=read_json(DETECT);qa=read_json(QA)
    archive=read_json(PRIOR/DETECT.name)
    if det.get("status")!="TRACKED" or det.get("passed") is not True:
        raise RuntimeError("Current detection record not the known repaired result")
    if det.get("version")!=EXPECTED_BLUR_VERSION:
        raise RuntimeError("Cigarette detection engine version changed")
    if not (int(det.get("raw_detection_count") or 0)==2 and
            int(det.get("confirmed_track_count") or 0)==1 and
            int(det.get("interval_count") or 0)==3):
        raise RuntimeError("Current detection count changed")
    if det.get("original_detection_report_sha256")!=sha(PRIOR/DETECT.name):
        raise RuntimeError("Original detection evidence SHA changed")
    if archive.get("passed") is not False or archive.get("status")!="AMBIGUOUS":
        raise RuntimeError("Archived detection evidence not the known ambiguous original")
    if int(archive.get("raw_detection_count") or 0)!=2 or len(archive.get("rejected_tracks") or [])!=1:
        raise RuntimeError("Archive lacks exactly two known false-positive hits")
    if len((archive["rejected_tracks"][0].get("hits") or []))!=2:
        raise RuntimeError("Archive does not contain the two original microphone observations")
    if qa.get("passed") is not True or int(qa.get("overlay_count") or 0)!=3:
        raise RuntimeError("Original structural QA is not expected PASS for 3 overlays")
    if HOLD.exists() or ROOT_HOLD.exists():
        raise RuntimeError("Quarantine marker already present but active delivery exists; manual audit required")
    return audit,det,qa,original_bytes

def update_status(old,now,kind):
    out=copy.deepcopy(old)
    out.update({
        "passed":False,
        "status":"SEMANTIC_HOLD_MICROPHONE_FALSE_POSITIVE",
        "failures":[ERROR],
        "semantic_visual_qa":"FAIL_KNOWN_FALSE_POSITIVE",
        "reviewed_window_sec":REVIEWED_INTERVAL,
        "reviewed_frames":24,
        "production_release_allowed":False,
        "semantic_audit_at_utc":now,
        "semantic_hold_reason":"Archived detection corresponded to the static decorative microphone mark, not a cigarette. Full 886_5 dialogue has not been audited for actual cigarettes.",
    })
    if kind=="detector":
        out["confirmed_track_count"]=0
        out["tracks"]=[]
        out["interval_count"]=0
        out["intervals"]=[]
        out["unconfirmed_detection_count"]=2
        out["evidence_source"]="ARCHIVED_TWO_FALSE_CIGARETTE_HITS_MICROPHONE_CONFIRMED_VISUALLY"
    return out

def build_hold(now,backup,audit):
    return {
      "schema":SCHEMA,"created_at_utc":now,
      "contour":"auto_edit","stream":"886","dialogue":"886_5",
      "status":"QUARANTINED_NOT_READY_FOR_PUBLICATION",
      "semantic_cigarette_detection":"FAIL_KNOWN_FALSE_POSITIVE_MICROPHONE",
      "human_reviewed_real_frames":24,
      "reviewed_window_sec":REVIEWED_INTERVAL,
      "all_dialogue_cigarette_presence":"NOT_YET_VERIFIED",
      "removed_misapplied_cigarette_blur_overlays":audit["removed_blur_overlays"],
      "original_source_audio_modified":False,"source_video_modified":False,
      "other_dialogues_modified":False,
      "clean_xml_reconstructed_from_verified_preblur_backup":True,
      "primary_xml_withheld":True,
      "clean_xml_for_semantic_review":str(backup/"CLEAN_XML_PENDING_SEMANTIC_REVIEW.xml"),
      "delivered_xml_withheld":True,
      "backup_directory":str(backup),
      "do_not_publish":True,
      "release_requires":"FULL_886_5_SEMANTIC_CIGARETTE_FRAME_REVIEW",
      "no_whole_frame_blur":True,
    }

def backed_up(backup):
    originals={"primary.xml":PRIMARY,"delivered.xml":DELIVERED,
               "detections.json":DETECT,"qa.json":QA}
    proofs={}
    for filename,source in originals.items():
        destination=backup/filename
        shutil.copy2(source,destination)
        proofs[filename]={"source":str(source),"sha256":sha(source)}
        if sha(destination)!=proofs[filename]["sha256"]:
            raise RuntimeError("Backup integrity mismatch for "+str(source))
    save_json(backup/"ORIGINAL_FILE_PROOFS.json",proofs)
    return originals,proofs

def safe_replace_bytes(dest,payload):
    with tempfile.NamedTemporaryFile(prefix="._RG8865_",suffix=".tmp",
                                     dir=str(dest.parent),delete=False) as f:
        temp=Path(f.name)
        f.write(payload)
    try:
        os.replace(temp,dest)
    finally:
        if temp.exists():temp.unlink()

def restore_from_backup(backup):
    names={"primary.xml":PRIMARY,"delivered.xml":DELIVERED,
           "detections.json":DETECT,"qa.json":QA}
    failures=[]
    for filename,target in names.items():
        source=backup/filename
        try:safe_replace_bytes(target,source.read_bytes())
        except Exception as exc:failures.append({"path":str(target),"reason":str(exc)})
    for target in (HOLD,ROOT_HOLD):
        try:target.unlink(missing_ok=True)
        except Exception as exc:failures.append({"path":str(target),"reason":str(exc)})
    return failures

def apply():
    from rg_production_stability import acquire_stream_lock,release_stream_lock
    lock=acquire_stream_lock("886",owner_pid=os.getpid(),
                             owner="RG 886_5 microphone false-positive semantic quarantine")
    try:
        audit,det,qa,original_bytes=preflight()
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        dest=DATA/"release_backups"/("PRE_886_5_MICROPHONE_SEMANTIC_HOLD_"+dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        dest.mkdir(parents=True,exist_ok=False)
        originals,proofs=backed_up(dest)
        # Preserve both original falsely labelled hits as a local negative
        # regression fixture. Never blanket-ban the microphone region:
        # a genuine cigarette may appear there later.
        archived=read_json(PRIOR/DETECT.name)
        save_json(dest/"MICROPHONE_KNOWN_NEGATIVE_FIXTURE.json",{
           "schema":"RG_CIGARETTE_MICROPHONE_NEGATIVE_FIXTURE_V1",
           "stream":"886","dialogue":"886_5",
           "reviewed_window_sec":REVIEWED_INTERVAL,
           "visual_label":"MICROPHONE_MARK_NOT_CIGARETTE",
           "label_source":"User-confirmed contact sheets 01-04",
           "archived_detector_hits":archived["rejected_tracks"][0]["hits"],
           "do_not_create_global_location_exclusion":True,
           "requires_semantic_detector_and_actual_video_labels":True,
           "production_adoption":False
        })
        # Source audio/other video and both archive copies validated *before* changes.
        new_det=update_status(det,now,"detector")
        new_qa=update_status(qa,now,"qa")
        hold=build_hold(now,dest,audit)
        # Prewrite stage: no output can ever claim semantic PASS after this.
        staged_data={
            DETECT:json.dumps(new_det,ensure_ascii=False,indent=2).encode("utf-8"),
            QA:json.dumps(new_qa,ensure_ascii=False,indent=2).encode("utf-8"),
            HOLD:json.dumps(hold,ensure_ascii=False,indent=2).encode("utf-8"),
            ROOT_HOLD:json.dumps(hold,ensure_ascii=False,indent=2).encode("utf-8"),
        }
        check_process_idle()
        if any(sha(p)!=proofs[k]["sha256"] for k,p in originals.items()):
            raise RuntimeError("886_5 was concurrently modified - refused")
        try:
            for p,b in staged_data.items():
                safe_replace_bytes(p,b)
            # Delete the published path by safely moving it to the VERIFIED BACKUP folder.
            # It cannot be accidentally picked up as a finished dialogue on next import.
            withheld=dest/"WITHHELD_PREVIOUS_DELIVERY.xml"
            os.replace(DELIVERED,withheld)
            if sha(withheld)!=proofs["delivered.xml"]["sha256"]:
                raise RuntimeError("Withheld delivery checksum mismatch")
            safe_replace_bytes(PRIMARY,original_bytes)
            if sha(PRIMARY)!=sha(PRIOR/PRIMARY.name):
                raise RuntimeError("Clean baseline restore checksum mismatch")
            # Withhold the primary too: Studio can discover RG_EDITED_886_5.xml
            # directly in APP, even when APP/886 copy has been removed.
            clean_held=dest/"CLEAN_XML_PENDING_SEMANTIC_REVIEW.xml"
            os.replace(PRIMARY,clean_held)
            if sha(clean_held)!=sha(PRIOR/PRIMARY.name):
                raise RuntimeError("Withheld clean XML checksum mismatch")
            if DELIVERED.exists() or PRIMARY.exists():
                raise RuntimeError("Candidate dialogue XML still discoverable in app ready folders")
            if read_json(DETECT).get("passed") is not False or read_json(QA).get("passed") is not False:
                raise RuntimeError("Semantic QA not invalidated")
            if not read_json(HOLD).get("do_not_publish"):
                raise RuntimeError("Fail-closed HOLD marker missing")
        except BaseException:
            failed=restore_from_backup(dest)
            if failed:
                # Preserve visible alert on non-atomic rollback failures.
                try:save_json(HOLD,dict(hold,status="ROLLBACK_INCOMPLETE",rollback_errors=failed))
                except Exception:pass
            raise RuntimeError("Quarantine transaction failed; rollback errors: "+repr(failed))
        return {
           "schema":SCHEMA,"status":"QUARANTINED",
           "contour":"auto_edit","stream":"886","dialogue":"886_5",
           "misplaced_microphone_blur_overlays_removed":3,
           "clean_xml_restored":True,
           "structural_xml_audit":audit,
           "detector_semantic_qa":"FAIL",
           "blur_qa_passed":False,
           "previous_delivered_xml_withheld":True,
           "previous_primary_xml_withheld":True,
           "clean_xml_held_for_review":str(dest/"CLEAN_XML_PENDING_SEMANTIC_REVIEW.xml"),
           "release_allowed":False,
           "full_dialogue_cigarette_audit":"NOT_RUN",
           "audio_unchanged":True,"original_video_unchanged":True,
           "other_dialogues_unchanged":True,
           "source_media_reprocessed":False,
           "backup":str(dest),
           "primary_xml":None,
           "hold_marker":str(HOLD),
           "next":"Review whole dialogue independently for genuine cigarettes; no stream rerun."
        }
    finally:
        release_stream_lock("886",str((lock or {}).get("run_id") or ""))

def self_test():
    def mk(blur=False,extras=()):
        root=ET.Element("xmeml")
        seq=ET.SubElement(root,"sequence")
        med=ET.SubElement(seq,"media")
        aud=ET.SubElement(med,"audio")
        track=ET.SubElement(aud,"track")
        ET.SubElement(track,"clipitem",{"id":"audio-1"})
        vid=ET.SubElement(med,"video")
        t=ET.SubElement(vid,"track")
        c=ET.SubElement(t,"clipitem",{"id":"original-1"})
        ET.SubElement(c,"name").text="source.mp4"
        if blur:
            tr=ET.SubElement(vid,"track")
            ET.SubElement(tr,"enabled").text="TRUE"
            for index in (1,2,3):
                clip=ET.SubElement(tr,"clipitem",{"id":f"rg-cigarette-{index}"})
                ET.SubElement(clip,"start").text=str(index)
                ET.SubElement(clip,"end").text=str(index+1)
                for name in ("crop","Gaussian Blur",*extras):
                    f=ET.SubElement(clip,"filter")
                    e=ET.SubElement(f,"effect")
                    ET.SubElement(e,"effectid").text=name
                    if name=="crop":
                        for typ,val in [("left",23),("right",73),("top",47),("bottom",46)]:
                            p=ET.SubElement(e,"parameter")
                            ET.SubElement(p,"parameterid").text=typ
                            ET.SubElement(p,"value").text=str(val)
        return ET.tostring(root)
    clean=mk()
    dirty=mk(blur=True)
    assert check_xml_xml(dirty,clean)["removed_blur_overlays"]==3
    # Regression reproduces 886_5 guard failure: some Premiere clips
    # contain extra legitimate filters. The entire added track is removed.
    actual_like=mk(blur=True,extras=("basicmotion","opacity"))
    info=check_xml_xml(actual_like,clean)
    assert info["semantic_xml_equal_after_overlay_removal"] is True
    assert info["audio_identical"] is True
    assert info["original_video_tracks_identical"] is True
    assert info["removed_blur_overlays"]==3
    cases=[("no_blur",clean,clean),
           ("wrong_audio",None,clean),
           ("wrong_video",None,clean),
           ("missing_blur",None,clean),
           ("duplicate_crop",None,clean),
           ("unexpected_global_change",None,clean),
           ("wrong_clip_id",None,clean)]
    tampered=ET.fromstring(actual_like)
    tampered.find("./sequence/media/audio/track").set("mutated","1")
    cases[1]=("wrong_audio",ET.tostring(tampered),clean)
    tampered=ET.fromstring(actual_like)
    tampered.find("./sequence/media/video/track/clipitem/name").text="other.mp4"
    cases[2]=("wrong_video",ET.tostring(tampered),clean)
    tampered=ET.fromstring(actual_like)
    clip=tampered.findall("./sequence/media/video/track")[-1].find("clipitem")
    for ef in clip.findall("filter"):
        if ef.findtext("effect/effectid")=="Gaussian Blur":
            clip.remove(ef)
            break
    cases[3]=("missing_blur",ET.tostring(tampered),clean)
    tampered=ET.fromstring(actual_like)
    clip=tampered.findall("./sequence/media/video/track")[-1].find("clipitem")
    for ef in clip.findall("filter"):
        if ef.findtext("effect/effectid")=="crop":
            clip.append(copy.deepcopy(ef))
            break
    cases[4]=("duplicate_crop",ET.tostring(tampered),clean)
    tampered=ET.fromstring(actual_like)
    tampered.find("sequence").set("changed","1")
    cases[5]=("unexpected_global_change",ET.tostring(tampered),clean)
    tampered=ET.fromstring(actual_like)
    tampered.findall("./sequence/media/video/track")[-1].find("clipitem").set("id","unexpected-id")
    cases[6]=("wrong_clip_id",ET.tostring(tampered),clean)
    for label,untrusted,baseline in cases:
        try:
            check_xml_xml(untrusted,baseline)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Unsafe XML passed quarantine preflight: "+label)
    print("RG_886_5_MICROPHONE_FALSE_POSITIVE_LOCAL_XML_GATES_V2: PASS",flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--preflight",action="store_true")
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        self_test()
        return
    if args.preflight:
        print("=== RG 886_5 MIC QUARANTINE FULL READ-ONLY PREFLIGHT ===",flush=True)
        audit,det,qa,clean=preflight()
        print("=== RG 886_5 MIC QUARANTINE PREFLIGHT READY ===",flush=True)
        print(json.dumps({
           "status":"PREFLIGHT_READY",
           "current_primary_sha256":sha(PRIMARY),
           "delivered_sha256":sha(DELIVERED),
           "clean_backed_up_sha256":sha(PRIOR/PRIMARY.name),
           "validated_overlay_count":audit["removed_blur_overlays"],
           "actual_effect_stacks":audit["overlay_details"],
           "whole_xml_matches_original_after_overlay_removal":
             audit["semantic_xml_equal_after_overlay_removal"],
           "audio_unchanged":audit["audio_identical"],
           "other_video_unchanged":audit["original_video_tracks_identical"],
           "no_changes_performed":True,
           "release_allowed":False
         },ensure_ascii=False,indent=2),flush=True)
        return
    if not args.apply:
        raise RuntimeError("Must explicitly supply --apply to change 886_5, or --self-test")
    print("=== RG 886_5 MIC BLUR QUARANTINE PREFLIGHT ===",flush=True)
    sys.path.insert(0,str(APP))
    report=apply()
    print("=== RG 886_5 MIC BLUR QUARANTINE RESULT ===",flush=True)
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("=== RG 886_5 MIC BLUR QUARANTINE STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","reason":str(exc),
              "full_stream_reprocessed":False},ensure_ascii=False,indent=2),flush=True)
        raise SystemExit(2)
