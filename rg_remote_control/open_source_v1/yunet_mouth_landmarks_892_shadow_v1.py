#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCV Zoo YuNet face/mouth-landmark diagnostic on 60 REAL 892 frames.

NO BLUR and NO automatic release. Never edits video, audio, Premiere XML,
Studio, or 886_5 quarantine. Mouth landmarks do not detect smoke or smoking.
Face detector model must exist offline and have exact pinned SHA-256.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import zipfile
from datetime import datetime, timezone

ROOT=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
SOURCE=ROOT/"positive_892_015841_v1"/"892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
TRACK=ROOT/"sam2_video_track_892_015841_v2_full_mask"/"RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip"
MODEL=ROOT/"model_cache_yunet_v1"/"face_detection_yunet_2023mar.onnx"
HOLD=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json")
OUT=ROOT/"yunet_mouth_892_real_60frame_shadow_v1"
MODEL_SHA="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
VIDEO_SHA="bf2e3e585afeaa0b0ba3c347066a6ca1adcacfec282cba691cc7ec9d1ae3b49c"
TRACK_SHA="2d88cf9d763d9c885702a7cc8f254fe9dba75d000de616df5781f28af2e68044"
SCHEMA="RG_YUNET_892_REAL_MOUTH_LANDMARKS_SHADOW_V1"
CROP=(1100,270,1650,710)
COUNT=60
SCALE=.65

def sha(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open("rb") as fp:
        for b in iter(lambda:fp.read(1<<20),b""):
            h.update(b)
    return h.hexdigest()

def mouth_from_yunet(face_row,scale):
    """YuNet row: x y w h, right eye, left eye, nose, mouth corners, score."""
    if face_row is None or len(face_row)!=15:
        return None
    row=[float(x) for x in face_row]
    if not .0<=row[14]<=1.0 or row[2]<=0 or row[3]<=0:
        return None
    left=(row[10]/scale,row[11]/scale)
    right=(row[12]/scale,row[13]/scale)
    x=(left[0]+right[0])/2.0
    y=(left[1]+right[1])/2.0
    if not (0<=x<550 and 0<=y<440):
        return None
    return {"mouth_center_xy":[round(x,2),round(y,2)],
            "mouth_corners_xy":[[round(v,2) for v in left],
                                [round(v,2) for v in right]],
            "face_bbox_xywh":[round(row[j]/scale,2) for j in range(4)],
            "face_score":round(row[14],5),
            "mouth_region_estimated_not_pixel_truth":True}

def selftest():
    row=[100,70,180,180,140,130,210,130,180,165,170,215,205,216,.93]
    result=mouth_from_yunet(row,1.0)
    assert result["mouth_center_xy"]==[187.5,215.5]
    assert mouth_from_yunet(row[:14],1.0) is None
    assert mouth_from_yunet(None,1.0) is None
    assert SCHEMA.endswith("SHADOW_V1")
    print("RG_YUNET_892_MOUTH_LANDMARK_SHADOW_AND_FAIL_CLOSED_SELFTEST: PASS")

def guarded_real_preflight():
    if OUT.exists():
        raise RuntimeError("Existing result: refuse overwriting real QA")
    for p,digest in ((SOURCE,VIDEO_SHA),(TRACK,TRACK_SHA),(MODEL,MODEL_SHA)):
        if not p.is_file() or sha(p)!=digest:
            raise RuntimeError("Missing/changed exact input sha256: "+str(p))
    if MODEL.stat().st_size!=232589:
        raise RuntimeError("YuNet file wrong size; probably downloaded Git LFS pointer")
    if not HOLD.is_file():
        raise RuntimeError("886_5 microphone quarantine missing")
    hold=json.loads(HOLD.read_text(encoding="utf-8-sig"))
    for k,v in (("schema","RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1"),
                ("do_not_publish",True),
                ("primary_xml_withheld",True),
                ("delivered_xml_withheld",True)):
        if hold.get(k)!=v:
            raise RuntimeError("886_5 quarantine validation failed: "+k)

def run():
    guarded_real_preflight()
    import cv2
    import numpy as np
    with zipfile.ZipFile(TRACK) as z:
        if z.testzip() is not None:
            raise RuntimeError("SAM2 source ZIP CRC failed")
        track=json.loads(z.read("report.json"))
        if track.get("schema")!="RG_SAM2_892_REAL_VIDEO_TRACK_SHADOW_V2_FULL_MASK":
            raise RuntimeError("Unexpected mask report source")
        if track.get("frames")!=13 or track.get("release_allowed") is not False:
            raise RuntimeError("Unexpected mask frame count / unsafe source")
        cigar_points=np.float32([m["center_xy"] for m in track["frame_metrics"]])
    cap=cv2.VideoCapture(str(SOURCE))
    if not cap.isOpened() or round(cap.get(cv2.CAP_PROP_FPS))!=30:
        raise RuntimeError("Real positive video not 30fps")
    x1,y1,x2,y2=CROP
    w,h=int((x2-x1)*SCALE),int((y2-y1)*SCALE)
    det=cv2.FaceDetectorYN.create(str(MODEL),"",(w,h),score_threshold=.55,nms_threshold=.3,top_k=200)
    if det is None:
        raise RuntimeError("YuNet face detector could not load")
    OUT.mkdir(parents=True)
    out_video=OUT/"RG_892_YUNET_REAL_MOUTH_LANDMARKS_60F_SHADOW.mp4"
    writer=cv2.VideoWriter(str(out_video),cv2.VideoWriter_fourcc(*"mp4v"),30,(550,472))
    if not writer.isOpened():
        raise RuntimeError("No local diagnostic writer")
    rows=[];photos=[]
    cap.set(cv2.CAP_PROP_POS_FRAMES,360)
    try:
        for n in range(COUNT):
            ok,full=cap.read()
            if not ok or full.shape[:2]!=(1080,1920):
                raise RuntimeError("Real diagnostic frame unavailable at "+str(n))
            im=full[y1:y2,x1:x2].copy()
            scaled=cv2.resize(im,(w,h))
            _,faces=det.detect(scaled)
            if faces is None or len(faces)==0:
                landmark=None
            else:
                # Highest score face only. Never infer identity from lips alone.
                candidate=faces[int(np.argmax(faces[:,14]))]
                landmark=mouth_from_yunet(candidate,SCALE)
            point_n=n/5
            a=int(point_n)
            b=min(a+1,12)
            t=point_n-a
            cigar_xy=(1-t)*cigar_points[a]+t*cigar_points[b]
            out=im.copy()
            cigar_local=(int(cigar_xy[0]-x1),int(cigar_xy[1]-y1))
            cv2.circle(out,cigar_local,7,(20,220,220),2)
            row={"frame_index":n,"relative_time_sec":round(12+n/30,5),
                 "mouth_landmarks_found":landmark is not None,
                 "cigarette_sam2_centroid_xy":[round(float(q),2) for q in cigar_xy],
                 "cigarette_identity_from_sam2_alone_not_approved":True,
                 "automatic_blur_allowed":False}
            if landmark is not None:
                px,py=map(int,landmark["mouth_center_xy"])
                cv2.ellipse(out,(px,py),(36,24),0,0,360,(225,40,220),2)
                row.update(landmark)
                row["distance_mouth_to_sam2_centroid_px"]=round(float(np.linalg.norm(
                    np.float32([px,py])-np.float32(cigar_local))),2)
            else:
                row["status"]="MOUTH_UNDETECTED_REVIEW_REQUIRED"
            screen=np.zeros((472,550,3),dtype=np.uint8)
            screen[:440]=out
            cv2.putText(screen,f"892 {12+n/30:.3f}s YuNet MOUTH - SHADOW ONLY",
                        (5,458),cv2.FONT_HERSHEY_SIMPLEX,.56,(248,248,248),1,cv2.LINE_AA)
            writer.write(screen)
            if n in (0,10,20,30,40,50,59):
                filename="QA_YUNET_MOUTH_%02d.jpg"%n
                if not cv2.imwrite(str(OUT/filename),screen):
                    raise RuntimeError("Cannot save frame")
                photos.append(filename)
            rows.append(row)
    finally:
        cap.release()
        writer.release()
    if sha(SOURCE)!=VIDEO_SHA:
        raise RuntimeError("Original positive clip changed")
    found=sum(int(r["mouth_landmarks_found"]) for r in rows)
    report={"schema":SCHEMA,"created_utc":datetime.now(timezone.utc).isoformat(),
        "status":"YUNET_FACIAL_LANDMARK_REAL_QA_ONLY_RELEASE_BLOCKED",
        "model":"opencv/opencv_zoo face_detection_yunet_2023mar.onnx",
        "license":"MIT - Shiqi Yu; see upstream LICENSE",
        "model_sha256":MODEL_SHA,"model_size_bytes":232589,
        "input_stream":"892","source_frame_offset":360,
        "frames_total":COUNT,"fps":30,
        "mouth_landmarks_found":found,"mouth_landmarks_missing":COUNT-found,
        "smoke_detector_validated":False,"hand_detector_validated":False,
        "cigarette_only_sam2_identity_sufficient":False,
        "all_4_smoking_zones_verified":False,
        "negative_8865_full_model_motion_test_passed":False,
        "production_release_allowed":False,"automatic_blur_allowed":False,
        "886_5_quarantine_unchanged":True,
        "source_video_modified":False,"source_audio_modified":False,
        "Premiere_XML_modified":False,"Studio_modified":False,
        "frames":rows}
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    with zipfile.ZipFile(OUT/"RG_892_YUNET_MOUTH_SHADOW_RESULT_V1.zip","w",zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        z.write(out_video,out_video.name)
        z.write(OUT/"report.json","report.json")
        for name in photos:z.write(OUT/name,name)
    with zipfile.ZipFile(OUT/"RG_892_YUNET_MOUTH_SHADOW_RESULT_V1.zip") as z:
        if z.testzip() is not None:raise RuntimeError("Output ZIP corrupt")
    print("=== REAL YUNET MOUTH SHADOW (NOT PRODUCTION) ===")
    print(json.dumps({"status":report["status"],"face_mouth_found":found,
                      "frames":COUNT,
                      "zip":str(OUT/"RG_892_YUNET_MOUTH_SHADOW_RESULT_V1.zip"),
                      "production_release_allowed":False},ensure_ascii=False,indent=2))

if __name__=="__main__":
    try:
        ap=argparse.ArgumentParser()
        ap.add_argument("--self-test",action="store_true")
        ap.add_argument("--run",action="store_true")
        a=ap.parse_args()
        if a.self_test:selftest()
        elif a.run:run()
        else:ap.error("Use --self-test or --run")
    except Exception as e:
        print("RG_YUNET_MOUTH_SHADOW_STOPPED: "+str(e))
        raise SystemExit(2)
