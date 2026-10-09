#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only baseline YOLOWorld comparison: genuine cigarette 892 vs mic 886.

PRODUCTION NEVER CHANGED. Does not assert independent cigarette identity, or
publish, remove/edit blur, or train models. Uses EXISTING installed worker and
model in a subprocess, output only inside F:/RG_AUTO_EDIT/.../oss_shadow/.
Self-test uses no video, model, CUDA, filesystem writes or external imports.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

SCHEMA="RG_CIGARETTE_892_POSITIVE_886_MICROPHONE_PAIR_BASELINE_V1"
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
SHADOW=DATA/"oss_shadow"
OUT=SHADOW/"cigarette_892_positive_vs_886_microphone_v1"
POS=SHADOW/"positive_892_015841_v1"/"892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
POS_MANIFEST=SHADOW/"positive_892_015841_v1"/"manifest.json"
NEG=Path(r"\\Desktop-v7gg0en\record\886.mp4")
HOLD=APP/"886"/"RG_EDITED_886_5.SEMANTIC_HOLD.json"
CONFIG=APP/"rg_auto_edit_config.json"
DETECT_MANIFEST=DATA/"cigarette_detector_v1.json"
WORKER=APP/"rg_cigarette_detector_worker.py"
ZIP="RG_CIGARETTE_892_VS_886_YOLOWORLD_BASELINE_v1.zip"
NEG_WINDOW=(9558.9,9561.2)
POS_WINDOW=(0.0,24.0)

def readj(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def hashfile(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def check_path(path):
    if not path.is_file():raise RuntimeError("Prerequisite not found: "+str(path))

def track_media(path):
    check_path(path)
    return {"size":path.stat().st_size,"mtime_ns":path.stat().st_mtime_ns}

def verify_state():
    for f in (RT,POS,POS_MANIFEST,NEG,HOLD,CONFIG,DETECT_MANIFEST,WORKER):
        check_path(f)
    if (APP/"RG_EDITED_886_5.xml").exists() or (APP/"886"/"RG_EDITED_886_5.xml").exists():
        raise RuntimeError("886_5 has unexpectedly reappeared in Studio ready folders")
    h=readj(HOLD)
    for key,val in {
      "schema":"RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1",
      "do_not_publish":True,
      "primary_xml_withheld":True,
      "delivered_xml_withheld":True,
      }.items():
        if h.get(key)!=val:raise RuntimeError("886_5 hold mismatch: "+key)
    meta=readj(POS_MANIFEST)
    if (meta.get("schema")!="RG_AUTO_EDIT_892_CIGARETTE_REAL_GOLD_CAPTURE_V1" or
        meta.get("stream")!="892" or meta.get("original_timecode")!="01:58:41" or
        meta.get("cigarette_semantically_confirmed") is not False or
        meta.get("studio_modified") is not False):
        raise RuntimeError("892 positive reference manifest not the pinned review pack")
    if (not (0<POS.stat().st_size<200*1024*1024) or
        not (1e6<NEG.stat().st_size)):
        raise RuntimeError("Unexpected positive/negative original video sizes")
    manifest=readj(DETECT_MANIFEST)
    site=Path(manifest.get("worker_site") or DATA/"workers"/"cigarette_blur"/"site")
    model=Path(manifest.get("model") or DATA/"models"/"cigarette_blur"/"yolov8s-worldv2.pt")
    if not site.is_dir():raise RuntimeError("Installed detector worker site missing")
    check_path(model)
    cfg=readj(CONFIG)
    opts=dict(cfg.get("cigarette_blur") or {})
    if not opts.get("mandatory",False) or not opts.get("fail_closed",False):
        raise RuntimeError("Production mandatory/fail_closed config is not enabled")
    if opts.get("version")!="RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2":
        raise RuntimeError("Detector configuration version changed since 886_5 audit")
    return site,model,opts

def run_worker(name,video,window,site,model,opts,temp):
    payload={"video":str(video),"ranges":[{"start":window[0],"end":window[1]}],
             "opts":opts,"model":str(model)}
    input_path=temp/(name+"_input.json")
    output_path=temp/(name+"_detections.json")
    input_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    env=os.environ.copy()
    env["PYTHONUTF8"]="1"
    env["PYTHONIOENCODING"]="utf-8"
    env["PYTHONPATH"]=str(site)+os.pathsep+str(APP)
    env["YOLO_CONFIG_DIR"]=str(DATA/"models"/"cigarette_blur"/"config")
    cmd=[str(RT),"-u","-X","utf8",str(WORKER),
         "--input",str(input_path),"--output",str(output_path)]
    print("RG_PAIR|START|"+name+"|"+str(window),flush=True)
    p=subprocess.Popen(cmd,cwd=str(APP),env=env,
         stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
         text=True,encoding="utf-8",errors="replace",
         creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    lines=[]
    try:
        assert p.stdout is not None
        for line in p.stdout:
            line=line.strip()
            if line:lines.append(line)
            if line.startswith("RGCIGPROGRESS|") and len(lines)%24==0:
                print("RG_PAIR|"+name+"|"+line,flush=True)
        rc=p.wait(timeout=900)
    except BaseException:
        try:p.kill()
        except Exception:pass
        p.wait()
        raise
    if rc!=0 or not output_path.is_file():
        raise RuntimeError("Existing detector failed "+name+": "+" | ".join(lines[-8:]))
    raw=readj(output_path)
    if raw.get("passed") is not True:
        raise RuntimeError("Worker did not return valid diagnostics: "+name)
    if raw.get("version")!="RG_CIGARETTE_DETECTOR_WORKER_V1":
        raise RuntimeError("Worker version not expected")
    if raw.get("video")!=str(video):
        raise RuntimeError("Worker analyzed unexpected video source")
    samples=raw.get("frames") or []
    for frame in samples:
        t=float(frame["t"])
        if not window[0]-0.03<=t<=window[1]+0.03:
            raise RuntimeError("Worker returned out-of-scope source timestamp")
    count=sum(len(x.get("boxes") or []) for x in samples)
    if count!=int(raw.get("raw_detection_count",-1)):
        raise RuntimeError("Worker raw hit count disagrees with boxes")
    return raw,output_path

def summarize(pos,neg,opts):
    pf=pos.get("frames") or []
    nf=neg.get("frames") or []
    positive_t=[x for x in pf if 10.0<=float(x["t"])<=14.0]
    out={
      "schema":SCHEMA,"contour":"auto_edit",
      "status":"YOLOWORLD_BASELINE_SHADOW_ONLY",
      "executed_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
      "real_positive_stream":"892","positive_source_timecode":"01:58:41",
      "positive_window_clip_sec":list(POS_WINDOW),
      "negative_stream":"886","negative_identity":"MICROPHONE_MARK",
      "negative_source_window_sec":list(NEG_WINDOW),
      "positive_raw_detection_count":int(pos.get("raw_detection_count",0)),
      "positive_reported_candidate_frames":len(pf),
      "positive_reported_candidate_frames_near_1_58_41":len(positive_t),
      "negative_raw_detection_count":int(neg.get("raw_detection_count",0)),
      "negative_reported_candidate_frames":len(nf),
      "negative_any_cigarette_prediction_is_known_false_positive":bool(nf),
      "sample_fps_coarse":float(opts.get("coarse_fps",3.0)),
      "sample_fps_refine":float(opts.get("refine_fps",12.0)),
      "configured_confidence":float(opts.get("confidence",0.08)),
      "baseline_worker_version":pos.get("version"),
      "positive_video_decode_backends":pos.get("video_decode_backends"),
      "negative_video_decode_backends":neg.get("video_decode_backends"),
      "human_visual_positive_present":True,
      "human_visual_negative_present":True,
      "positive_candidates_semantically_verified":False,
      "positive_recall_measured":False,
      "negative_model_output_is_not_visual_truth":True,
      "independent_semantic_verifier_run":False,
      "all_892_frames_verified":False,
      "cigarette_only_masks_verified":False,
      "production_approved":False,
      "studio_modified":False,
      "source_video_modified":False,
      "original_audio_modified":False,
      "premiere_xml_modified":False,
      "quarantine_886_5_modified":False,
      "next":"Upload this ZIP for comparison of real cigarette detections with known microphone false positive. Evaluate independently, then design semantic verifier and motion-aware object-only mask.",
    }
    return out

def selftest():
    pos={"frames":[{"t":12.0,"boxes":[{"bbox":[1200,350,1240,370],"score":0.4}]}],
         "raw_detection_count":1,"version":"RG_CIGARETTE_DETECTOR_WORKER_V1"}
    neg={"frames":[{"t":9559.0,"boxes":[{"bbox":[100,100,120,120],"score":0.2}]}],
         "raw_detection_count":1}
    x=summarize(pos,neg,{"confidence":0.08})
    assert x["positive_reported_candidate_frames_near_1_58_41"]==1
    assert x["negative_any_cigarette_prediction_is_known_false_positive"]
    assert not x["positive_recall_measured"] and not x["independent_semantic_verifier_run"]
    assert not x["production_approved"] and not x["studio_modified"]
    assert list(NEG_WINDOW)==[9558.9,9561.2]
    assert list(POS_WINDOW)==[0.0,24.0]
    print("RG_892_886_REAL_CIGARETTE_VS_MIC_BASELINE_SELFTEST: PASS",flush=True)

def process():
    if OUT.exists():
        report=OUT/"summary.json"
        archive=OUT/ZIP
        if report.is_file() and archive.is_file():
            old=readj(report)
            if old.get("schema")==SCHEMA and not old.get("production_approved"):
                print("=== RG CIGARETTE BASELINE EXISTING SAFE REPORT ===",flush=True)
                print(json.dumps({
                  "status":old.get("status"),"archive":str(archive),
                  "positive_raw":old.get("positive_raw_detection_count"),
                  "negative_raw":old.get("negative_raw_detection_count"),
                  "production_modified":False},indent=2),flush=True)
                return
        raise RuntimeError("Previous partially saved report exists, not overwritten")
    site,model,opts=verify_state()
    before={str(p):track_media(p) for p in (POS,NEG)}
    staged=Path(tempfile.mkdtemp(prefix=".rg_cigarette_pair_",dir=str(SHADOW)))
    try:
        p,p_file=run_worker("POSITIVE_892",POS,POS_WINDOW,site,model,opts,staged)
        n,n_file=run_worker("NEGATIVE_886",NEG,NEG_WINDOW,site,model,opts,staged)
        for v in (POS,NEG):
            if track_media(v)!=before[str(v)]:
                raise RuntimeError("Source video metadata changed during isolated benchmark")
        verify_state()
        report=summarize(p,n,opts)
        summary=staged/"summary.json"
        summary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        archive=staged/ZIP
        with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            z.write(summary,"summary.json")
            z.write(p_file,"POSITIVE_892_raw.json")
            z.write(n_file,"NEGATIVE_886_raw.json")
        for test_file in (summary,p_file,n_file):
            if not test_file.is_file():raise RuntimeError("Incomplete output")
        shutil.copy2(summary,staged/"summary_backup.json")
        # Remove raw inputs from the exported output directory: source paths
        # already logged in original worker report; no need to preserve inputs.
        for tmp in (staged/"POSITIVE_892_input.json",staged/"NEGATIVE_886_input.json"):
            tmp.unlink(missing_ok=True)
        os.rename(staged,OUT)
        print("=== RG CIGARETTE 892 POSITIVE / 886 MICROPHONE BASELINE COMPLETE ===",flush=True)
        print(json.dumps({
          "status":report["status"],"positive_raw":report["positive_raw_detection_count"],
          "negative_raw":report["negative_raw_detection_count"],
          "positive_candidate_frames_at_user_timecode":report["positive_reported_candidate_frames_near_1_58_41"],
          "archive":str(OUT/ZIP),
          "semantic_verified":False,"production_modified":False,
          "release_allowed":False
        },ensure_ascii=False,indent=2),flush=True)
    finally:
        if staged.exists():shutil.rmtree(staged,ignore_errors=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--run",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        selftest()
        return
    if not args.run:
        raise RuntimeError("Use --self-test for offline QA or --run for read-only RTX baseline")
    process()

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("=== RG CIGARETTE PAIR BASELINE STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","reason":str(exc),
             "studio_modified":False,"source_video_modified":False,
             "premiere_xml_modified":False,"release_allowed":False
        },ensure_ascii=False,indent=2),flush=True)
        raise SystemExit(2)
