#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAM2 892 cigar CORE geometry experiment from existing authentic data.

SHADOW ONLY: no GPU, no internet, no installation, no audio/XML/Studio writes.
Never interprets a thin elongated mask as proof of cigarette identity. The
886_5 microphone decoration is a KNOWN hard negative for semantic approval.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, tempfile, zipfile, shutil
from datetime import datetime, timezone
import cv2
import numpy as np

SCHEMA="RG_SAM2_892_CIGARETTE_CORE_GEOMETRY_SHADOW_V1"
SAM2_SCHEMA="RG_SAM2_892_REAL_VIDEO_TRACK_SHADOW_V2_FULL_MASK"
GOLD_SCHEMA="RG_AUTO_EDIT_892_CIGARETTE_REAL_GOLD_CAPTURE_V1"
WIDTH,HEIGHT,NFRAMES,FIRST,STEP=1920,1080,13,360,5
MAX_ZIP_ITEM=45_000_000
HALF_WIDTH=7.5
MAX_AXIS_LENGTH=105.0
OFFSET_XY=(1180,310,1570,565)
CORE_NAME="RG_SAM2_892_CORE_GEOMETRY_SHADOW_V1.zip"

def checksum(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):
            h.update(b)
    return h.hexdigest()

def check_zip(z):
    names=z.namelist()
    if len(names)!=len(set(names)):raise ValueError("duplicate ZIP names")
    for item in z.infolist():
        p=pathlib.PurePosixPath(item.filename)
        if p.is_absolute() or ".." in p.parts or "\\" in item.filename:
            raise ValueError("unsafe ZIP member name")
        if item.file_size>MAX_ZIP_ITEM:
            raise ValueError("unbounded ZIP item")
    if z.testzip() is not None:raise ValueError("ZIP checksum corruption")

def require_892(motion,gold):
    if motion.get("schema")!=SAM2_SCHEMA or motion.get("video")!="892":
        raise ValueError("Unexpected SAM2 tracking ZIP schema")
    if motion.get("frames")!=NFRAMES or motion.get("fps")!=6:
        raise ValueError("Unexpected tracking sampling")
    for k in ("release_allowed","automatic_blur_allowed","original_audio_modified",
              "premiere_xml_modified","studio_modified","quarantine_886_5_modified"):
        if motion.get(k) is not False:raise ValueError("Unsafe tracking flag "+k)
    if gold.get("schema")!=GOLD_SCHEMA or gold.get("stream")!="892":
        raise ValueError("Unverified positive source: real 892 required")
    if gold.get("original_timecode")!="01:58:41" or gold.get("studio_modified") is not False:
        raise ValueError("Unexpected source timecode/provenance")
    if gold.get("cigarette_semantically_confirmed") is not False:
        raise ValueError("Conflicting unapproved positive baseline status")
    return True

def narrow_core(binary):
    """PCA narrow cigar-axis tube intersected with SAM2; never creates pixels.

    Geometry-only, not skin/smoke identity; human QA and independent identity
    remain essential. The chosen 7.5 pixel radius is EXPERIMENTAL on 1080p.
    """
    if binary.shape!=(HEIGHT,WIDTH):raise ValueError("Wrong full mask shape")
    y,x=np.where(binary)
    if len(x)<40:raise ValueError("Empty or tiny SAM2 candidate")
    xy=np.column_stack([x,y]).astype(np.float64)
    center=xy.mean(axis=0)
    centered=xy-center
    eigenvalues,eigenvectors=np.linalg.eigh(centered.T@centered/len(xy))
    direction=eigenvectors[:,-1]
    if direction[0]<0:direction=-direction
    ortho=np.array([-direction[1],direction[0]])
    along=centered@direction;across=centered@ortho
    begin,end=np.quantile(along,[.05,.95])
    median=float(np.median(across))
    inside=(along>=begin)&(along<=end)&(np.abs(across-median)<=HALF_WIDTH)
    result=np.zeros(binary.shape,dtype=np.uint8)
    result[y[inside],x[inside]]=255
    if np.any((result>0)&(~binary)):raise AssertionError("Unmasked pixels added")
    axis_len=float(end-begin)
    out=dict(original_pixels=int(len(x)),core_pixels=int(inside.sum()),
             core_percent_of_sam2=round(float(inside.sum()/len(x))*100,2),
             cigar_axis_length_px=round(axis_len,2),
             angle_degrees=round(float(np.degrees(np.arctan2(direction[1],direction[0]))),2),
             half_width_px=HALF_WIDTH,
             mask_centroid_xy=[round(float(v),2) for v in center],
             elongated_tube_geometry_only=True,
             cigarette_identity_verified=False,
             no_skin_overlap_verified=False,
             no_smoke_overlap_verified=False,
             automatic_blur_allowed=False)
    warnings=[]
    if axis_len>MAX_AXIS_LENGTH:warnings.append("AXIS_MAY_INCLUDE_SMOKE_OR_OTHER_OBJECT")
    if len(x)<500:warnings.append("UNSTABLE_TINY_INPUT")
    out["flags"]=warnings
    return result,out

def negative_semantic_gate(source_stream,manual_positive_approved=False):
    """A microphone-looking slender candidate is NEVER automatically positive."""
    if source_stream=="886":
        return dict(source_stream=source_stream,known_microphone_false_positive=True,
                    semantic_status="KNOWN_NEGATIVE_OR_UNVERIFIED",approved=False,
                    release_allowed=False)
    return dict(source_stream=source_stream,known_microphone_false_positive=False,
                semantic_status="SHADOW_REVIEW_REQUIRED",approved=False,
                release_allowed=False)

def selftest():
    assert not negative_semantic_gate("886")["approved"]
    assert not negative_semantic_gate("886",manual_positive_approved=True)["approved"]
    assert not negative_semantic_gate("892")["approved"]
    fake=np.zeros((HEIGHT,WIDTH),dtype=bool)
    cv2.line(fake.view(np.uint8),(1230,395),(1310,459),1,16)
    out,info=narrow_core(fake)
    assert 0<int(out.sum())<int(fake.sum()*255)
    assert info["core_pixels"]<info["original_pixels"]
    assert np.logical_and(out>0,~fake).sum()==0
    assert info["automatic_blur_allowed"] is False
    # A microphone decoration can look like the same narrow tube:
    # The geometry helper must NOT assign positive cigarette identity.
    microphone=np.zeros((HEIGHT,WIDTH),dtype=bool)
    cv2.line(microphone.view(np.uint8),(425,500),(515,585),1,16)
    fake_refine,fake_info=narrow_core(microphone)
    assert fake_info["cigarette_identity_verified"] is False
    assert not negative_semantic_gate("886")["release_allowed"]
    assert fake_refine.sum()>0   # deliberately plausible geometry, never semantically approved
    print("RG_SAM2_892_CIGARETTE_CORE_FALSE_MICROPHONE_SEMANTIC_GATE: PASS")

def annotate(frame,broad,core,idx,t):
    x1,y1,x2,y2=OFFSET_XY
    panels=[frame[y1:y2,x1:x2].copy() for _ in range(3)]
    for im,chosen,color in [(panels[1],broad[y1:y2,x1:x2],(250,225,20)),
                             (panels[2],core[y1:y2,x1:x2]>0,(20,190,250))]:
        im[chosen]=(im[chosen].astype(np.float32)*0.55+np.array(color)*0.45).astype(np.uint8)
    row=np.concatenate(panels,axis=1)
    cv2.rectangle(row,(0,0),(row.shape[1],32),(7,7,7),-1)
    label=f"892 {t:.3f}s #{idx:02d} ORIGINAL | SAM2 | TUBE ONLY - NOT APPROVED"
    cv2.putText(row,label,(7,24),cv2.FONT_HERSHEY_SIMPLEX,.57,(245,245,245),1,cv2.LINE_AA)
    return row

def run(samzip,goldzip,output):
    output=pathlib.Path(output)
    if output.exists():raise FileExistsError("Refuse overwriting existing evidence "+str(output))
    if not samzip.is_file() or not goldzip.is_file():raise ValueError("Two real input ZIPs required")
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(samzip) as z,zipfile.ZipFile(goldzip) as gz:
        check_zip(z);check_zip(gz)
        motion=json.loads(z.read("report.json"))
        gold=json.loads(gz.read("manifest.json"))
        require_892(motion,gold)
        meta=gold.get("video_clip") or {}
        mp4name="892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
        with tempfile.TemporaryDirectory(prefix="rg_892_core_shadow_",dir=str(output.parent)) as td:
            mp4=pathlib.Path(td)/"source_video_only.mp4"
            with gz.open(mp4name) as r,mp4.open("wb") as w:
                shutil.copyfileobj(r,w)
            source_sha=checksum(mp4)
            cap=cv2.VideoCapture(str(mp4))
            if not cap.isOpened():raise RuntimeError("Cannot decode video-only gold sample")
            if round(cap.get(cv2.CAP_PROP_FPS))!=30:raise ValueError("Unexpected gold FPS")
            if (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))!=(WIDTH,HEIGHT):
                raise ValueError("Wrong gold dimensions")
            qa=[];items=[];contact=[]
            try:
                for i in range(NFRAMES):
                    mask_name=f"review_frames/FULL_MASK_{i:02d}_1920x1080.png"
                    raw=np.frombuffer(z.read(mask_name),dtype=np.uint8)
                    img=cv2.imdecode(raw,cv2.IMREAD_GRAYSCALE)
                    if img is None or img.shape!=(HEIGHT,WIDTH) or not np.isin(img,[0,255]).all():
                        raise ValueError("Corrupt or nonbinary true SAM2 full mask")
                    row=motion["frame_metrics"][i]
                    if row["frame_idx"]!=i or np.count_nonzero(img)!=row["pixels"]:
                        raise ValueError("SAM2 mask does not match report")
                    core,info=narrow_core(img>0)
                    cap.set(cv2.CAP_PROP_POS_FRAMES,FIRST+STEP*i)
                    ok,frame=cap.read()
                    if not ok:raise RuntimeError("Gold frame read failed")
                    clock=12+STEP*i/30
                    comp=annotate(frame,img>0,core,i,clock)
                    qa.append(dict(frame_index=i,relative_clip_time_sec=round(clock,6),**info))
                    items.append((f"masks/CORE_{i:02d}_1920x1080.png",
                                  cv2.imencode(".png",core)[1].tobytes()))
                    items.append((f"comparison/FRAME_{i:02d}.jpg",
                                  cv2.imencode(".jpg",comp,[cv2.IMWRITE_JPEG_QUALITY,94])[1].tobytes()))
                    contact.append(cv2.resize(comp,(1170,255)))
            finally:
                cap.release()
            if checksum(mp4)!=source_sha:raise RuntimeError("Input gold mp4 mutated")
        canvas=np.zeros((7*255,2*1170,3),dtype=np.uint8)
        for i,item in enumerate(contact):
            y,x=divmod(i,2);canvas[y*255:(y+1)*255,x*1170:(x+1)*1170]=item
        image_bytes=cv2.imencode(".jpg",canvas,[cv2.IMWRITE_JPEG_QUALITY,89])[1].tobytes()
        items.append(("REVIEW_ALL_13_ORIGINAL_SAM2_CORE.jpg",image_bytes))
        report=dict(schema=SCHEMA,date_utc=datetime.now(timezone.utc).isoformat(),
                    source_stream="892",relative_times_sec=[12,14],frames=NFRAMES,
                    input_sam2_zip_name=samzip.name,input_gold_zip_name=goldzip.name,
                    source_clip_sha256=source_sha,
                    half_width_px=HALF_WIDTH,max_axis_length_px=MAX_AXIS_LENGTH,
                    row_qa=qa,known_negative_886_microphone_gate=negative_semantic_gate("886"),
                    independent_cigarette_identity_tested=False,
                    pixel_precision_recall_vs_manual_ground_truth_measured=False,
                    skin_smoke_bleed_eliminated=False,
                    single_frame_geometry_only=True,
                    temporal_tracking_proof_not_improved_by_refinement=True,
                    approved_for_blur=False,approved_for_studio=False,
                    production_release_allowed=False,original_video_modified=False,
                    original_audio_modified=False,premiere_xml_modified=False,
                    semantic_quarantine_886_5_unchanged=True)
        items.append(("report.json",json.dumps(report,ensure_ascii=False,indent=2).encode("utf-8")))
        temp=output.with_name(output.name+".tmp")
        with zipfile.ZipFile(temp,"w",zipfile.ZIP_DEFLATED,compresslevel=5) as dest:
            for name,data in items:dest.writestr(name,data)
        with zipfile.ZipFile(temp) as check:
            if check.testzip():raise RuntimeError("Generated ZIP invalid")
        temp.rename(output)
        print(json.dumps({"schema":SCHEMA,"status":"EXPERIMENTAL_CORE_MASKS_ONLY",
                          "frames":NFRAMES,"output":str(output),
                          "mean_percent_retained":round(float(np.mean([x["core_percent_of_sam2"] for x in qa])),2),
                          "frames_with_axis_smoke_flag":[x["frame_index"] for x in qa if x["flags"]],
                          "known_886_negative_release":False,
                          "auto_blur_allowed":False,"studio_modified":False},indent=2))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--sam2-zip",type=pathlib.Path)
    p.add_argument("--gold-zip",type=pathlib.Path)
    p.add_argument("--out",type=pathlib.Path)
    a=p.parse_args()
    if a.self_test:selftest()
    else:
        if not (a.sam2_zip and a.gold_zip and a.out):p.error("Both ZIPs and output required")
        run(a.sam2_zip,a.gold_zip,a.out)

if __name__=="__main__":
    try:main()
    except Exception as e:
        print("RG_SAM2_CORE_SHADOW_FAIL_CLOSED: "+str(e))
        raise SystemExit(2)
