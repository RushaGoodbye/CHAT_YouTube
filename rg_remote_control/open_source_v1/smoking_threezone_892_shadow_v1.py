#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UNAPPROVED three-zone 892 visual QA. No smoke detection or production modifications."""
from __future__ import annotations
import argparse, csv, datetime, hashlib, json, pathlib, shutil, sys, tempfile, zipfile

ROOT=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
SRC=ROOT/"positive_892_015841_v1"/"892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
MODEL=ROOT/"sam2_native_windows_892_v1"/"sam2.1_hiera_tiny.pt"
CONF=ROOT/"sam2_native_windows_892_v1"/"sam2_repo"/"sam2"/"configs"
YU=ROOT/"yunet_mouth_892_real_60frame_shadow_v1"/"RG_892_YUNET_MOUTH_SHADOW_RESULT_V1.zip"
HR=ROOT/"sam2_hand_892_60frame_reverse_shadow_v1"/"RG_892_HAND_60FRAME_REVERSE_SHADOW_V1.zip"
HOLD=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json")
OUT=ROOT/"smoking_threezone_892_60frame_shadow_v1"
SRC_SHA="bf2e3e585afeaa0b0ba3c347066a6ca1adcacfec282cba691cc7ec9d1ae3b49c"
MODEL_SHA="7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
COUNT=60
FIRST=360
ROI=(1000,240,1740,850)
CIG=[(1248,423,1),(1290,459,0),(1200,425,0)]
HAND=[(1305,635,1),(1365,595,1),(1413,534,1),
      (1475,489,0),(1558,500,0),(1160,460,0),
      (1373,524,1),(1409,491,1),(1446,485,1),
      (1470,406,0),(1512,515,0)]

def sha(p):
    h=hashlib.sha256()
    with pathlib.Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()

def get_report(p,schema):
    with zipfile.ZipFile(p) as z:
        if z.testzip() is not None:raise RuntimeError("Reference ZIP CRC failed "+str(p))
        r=json.loads(z.read("report.json"))
    if r.get("schema")!=schema or len(r.get("frames",[]))!=COUNT:
        raise RuntimeError("Invalid reference report "+str(p))
    if r.get("production_release_allowed") is not False:
        raise RuntimeError("Unsafe reference release flag")
    return r

def validate():
    for p in (SRC,MODEL,YU,HR,HOLD,CONF/"sam2.1/sam2.1_hiera_t.yaml"):
        if not p.is_file():raise RuntimeError("Missing input: "+str(p))
    if OUT.exists():raise RuntimeError("QA output already exists; refuse overwrite")
    if sha(SRC)!=SRC_SHA or sha(MODEL)!=MODEL_SHA:
        raise RuntimeError("Pinned source/model hash mismatch")
    h=json.loads(HOLD.read_text(encoding="utf-8-sig"))
    for k,v in (("schema","RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1"),
                ("do_not_publish",True),("primary_xml_withheld",True),
                ("delivered_xml_withheld",True)):
        if h.get(k)!=v:raise RuntimeError("886_5 quarantine invalid "+k)
    yu=get_report(YU,"RG_YUNET_892_REAL_MOUTH_LANDMARKS_SHADOW_V1")
    hand=get_report(HR,"RG_892_HAND_60FRAME_REVERSE_SHADOW_V1")
    if [f.get("frame_index") for f in yu["frames"]]!=list(range(COUNT)):
        raise RuntimeError("YuNet frame index mismatch")
    if [f.get("source_frame") for f in hand["frames"]]!=list(range(419,359,-1)):
        raise RuntimeError("Reverse hand frame index mismatch")
    if hand.get("source_sha256")!=SRC_SHA or yu.get("source_frame_offset")!=FIRST:
        raise RuntimeError("Source/reference mismatch")
    return yu,hand,sha(HOLD)

def zones(cigar,hand,mouth,score):
    """Masks are QA estimates, never confirmed cigarette/finger/mouth identity."""
    import cv2,numpy as np
    if cigar.shape!=hand.shape or cigar.ndim!=2:raise RuntimeError("Mask shape mismatch")
    cig=(cigar>0)
    hh=(hand>0)
    zero=np.zeros(cig.shape,np.uint8)
    if not cig.any():
        return zero,zero.copy(),zero.copy(),["CIGARETTE_MASK_EMPTY"]
    cigar_mask=cv2.dilate(cig.astype(np.uint8),np.ones((7,7),np.uint8),iterations=1)
    dist=cv2.distanceTransform((~cig).astype(np.uint8),cv2.DIST_L2,3)
    contact=(hh & (dist<=48)).astype(np.uint8)
    mouth_mask=zero.copy()
    flags=[]
    if not contact.any():flags.append("HAND_CONTACT_NEIGHBORHOOD_EMPTY")
    if mouth is None or score is None or score<.70:
        flags.append("MOUTH_LANDMARK_UNRELIABLE")
    else:
        x,y=int(round(mouth[0]-ROI[0])),int(round(mouth[1]-ROI[1]))
        if not (0<=x<cig.shape[1] and 0<=y<cig.shape[0]):
            flags.append("MOUTH_OUTSIDE_ROI")
        else:
            yy,xx=np.nonzero(cig)
            if float(np.hypot(xx.mean()-x,yy.mean()-y))<=80:
                cv2.ellipse(mouth_mask,(x,y),(32,17),0,0,360,1,-1)
                flags.append("MOUTH_HEURISTIC_NOT_PIXEL_VERIFIED")
            else:
                flags.append("MOUTH_NOT_NEAR_CIGARETTE")
    return cigar_mask,contact,mouth_mask,flags

def test():
    import numpy as np
    c=np.zeros((120,160),np.uint8);c[48:54,70:77]=1
    h=np.zeros_like(c);h[52:80,75:103]=1;h[:20,:20]=1
    a,b,d,f=zones(c,h,(1075,290),.9)
    assert a.sum() and b.sum() and d.sum() and not b[1,1]
    a,b,d,f=zones(np.zeros_like(c),h,(1075,290),.9)
    assert not a.any() and not b.any() and not d.any()
    a,b,d,f=zones(c,h,(1075,290),.2)
    assert not d.any() and "MOUTH_LANDMARK_UNRELIABLE" in f
    print("RG_892_THREEZONE_SYNTHETIC_FAIL_CLOSED_SELFTEST: PASS")

def extract(stage):
    import cv2
    fwd=stage/"forward";rev=stage/"reverse"
    fwd.mkdir();rev.mkdir()
    cap=cv2.VideoCapture(str(SRC))
    try:
        if not cap.isOpened() or abs(cap.get(cv2.CAP_PROP_FPS)-30)>.1:
            raise RuntimeError("Source open/FPS wrong")
        if (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))!=(1920,1080):
            raise RuntimeError("Source resolution wrong")
        cap.set(cv2.CAP_PROP_POS_FRAMES,FIRST)
        for i in range(COUNT):
            ok,img=cap.read()
            if not ok or img.shape[:2]!=(1080,1920):
                raise RuntimeError("Source frame missing "+str(FIRST+i))
            if not cv2.imwrite(str(fwd/f"{i:05d}.jpg"),img,[cv2.IMWRITE_JPEG_QUALITY,93]):
                raise RuntimeError("Frame copy write failed")
    finally:cap.release()
    for i in range(COUNT):
        shutil.copyfile(fwd/f"{COUNT-1-i:05d}.jpg",rev/f"{i:05d}.jpg")
    return fwd,rev

def follow(predictor,folder,points,reverse,output):
    import numpy as np,cv2
    output.mkdir()
    st=predictor.init_state(str(folder),offload_video_to_cpu=True,
                            offload_state_to_cpu=True,async_loading_frames=False)
    try:
        predictor.add_new_points_or_box(st,frame_idx=0,obj_id=1,
            points=np.asarray([p[:2] for p in points],np.float32),
            labels=np.asarray([p[2] for p in points],np.int32))
        seen=set();stats={}
        for idx,ids,logits in predictor.propagate_in_video(st,start_frame_idx=0,
                                              max_frame_num_to_track=COUNT-1):
            idx=int(idx)
            if idx not in range(COUNT) or idx in seen or 1 not in ids:
                raise RuntimeError("SAM2 returned missing/duplicate frame or object")
            mask=(logits[list(ids).index(1)]>0).detach().cpu().numpy().squeeze().astype(np.uint8)
            if mask.shape!=(1080,1920):raise RuntimeError("Invalid SAM2 mask dimensions")
            x1,y1,x2,y2=ROI
            crop=mask[y1:y2,x1:x2]
            k=COUNT-1-idx if reverse else idx
            if not cv2.imwrite(str(output/f"{k:02d}.png"),crop*255):
                raise RuntimeError("SAM2 mask write failed")
            stats[k]={"area":int(mask.sum()),"roi_spill":int(mask.sum()-crop.sum())}
            seen.add(idx)
        if len(seen)!=COUNT:raise RuntimeError("SAM2 missed frames")
        return stats
    finally:
        predictor.reset_state(st)

def visualize(stage,fwd,cigar_stats,hand_stats,yu,old):
    import cv2,numpy as np
    x1,y1,x2,y2=ROI;w=x2-x1;h=y2-y1
    out=stage/"THREEZONE_892_UNAPPROVED_2S_NO_AUDIO.mp4"
    video=cv2.VideoWriter(str(out),cv2.VideoWriter_fourcc(*"mp4v"),30,(w*2,h))
    if not video.isOpened():raise RuntimeError("Preview writer failed")
    prior={r["source_frame"]:r for r in old["frames"]}
    all_rows=[];pics=[]
    try:
        for i in range(COUNT):
            frame=cv2.imread(str(fwd/f"{i:05d}.jpg"))
            original=frame[y1:y2,x1:x2].copy()
            cigar=cv2.imread(str(stage/"cigar_masks"/f"{i:02d}.png"),0)
            hand=cv2.imread(str(stage/"hand_masks"/f"{i:02d}.png"),0)
            if cigar is None or hand is None or cigar.shape!=(h,w) or hand.shape!=(h,w):
                raise RuntimeError("Missing saved SAM2 mask")
            m=yu["frames"][i]
            p=m.get("mouth_center_xy")
            p=([p[0]+1100,p[1]+270] if m.get("mouth_landmarks_found") and p else None)
            a,b,c,flags=zones(cigar,hand,p,m.get("face_score"))
            union=((a>0)|(b>0)|(c>0)).astype(np.uint8)
            display=original.copy()
            if union.any():
                smooth=cv2.GaussianBlur(original,(0,0),14)
                alpha=cv2.GaussianBlur(union.astype(np.float32),(19,19),4)[:,:,None]
                display=np.clip(original*(1-alpha)+smooth*alpha,0,255).astype(np.uint8)
            for color,mask in (((0,215,255),a),((50,230,50),b),((220,80,220),c)):
                contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(display,contours,-1,color,2)
            h_area=hand_stats[i]["area"]
            ref_area=prior[FIRST+i].get("pixels",0)
            if ref_area and abs(h_area-ref_area)/ref_area>.5:
                flags.append("HAND_AREA_MISMATCH_PRIOR_REFERENCE")
            if hand_stats[i]["roi_spill"]:flags.append("HAND_ROI_SPILL")
            if cigar_stats[i]["roi_spill"]:flags.append("CIGAR_ROI_SPILL")
            if cigar_stats[i]["area"]<10:flags.append("CIGARETTE_MASK_TINY")
            if cigar_stats[i]["area"]>8000:flags.append("CIGARETTE_MASK_OVERSIZE")
            flags.extend(("SMOKE_UNDETECTED","IDENTITY_NOT_INDEPENDENTLY_VERIFIED"))
            row={"source_frame":FIRST+i,"relative_time_sec":round((FIRST+i)/30,5),
                 "cigar_pixels":cigar_stats[i]["area"],"hand_pixels":h_area,
                 "hand_contact_candidate_pixels":int(b.sum()),
                 "mouth_guide_pixels":int(c.sum()),"union_pixels":int(union.sum()),
                 "face_score":m.get("face_score"),"flags":sorted(set(flags)),
                 "automatic_release_allowed":False}
            all_rows.append(row)
            if i in (0,10,20,30,40,50,59):
                name=f"QA_{FIRST+i}.jpg"
                if not cv2.imwrite(str(stage/name),np.concatenate((original,display),axis=1),
                                   [cv2.IMWRITE_JPEG_QUALITY,92]):
                    raise RuntimeError("QA JPG write failed")
                pics.append(name)
            cv2.putText(display,f"892 {12+i/30:.3f}s  QA ONLY - NO SMOKE DETECTION",
                        (7,h-16),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
            video.write(np.concatenate((original,display),axis=1))
    finally:video.release()
    with (stage/"metrics.csv").open("w",newline="",encoding="utf-8") as fd:
        keys=["source_frame","relative_time_sec","cigar_pixels","hand_pixels",
              "hand_contact_candidate_pixels","mouth_guide_pixels","union_pixels",
              "face_score","flags","automatic_release_allowed"]
        writer=csv.DictWriter(fd,fieldnames=keys);writer.writeheader()
        for item in all_rows:
            writer.writerow({**item,"flags":"|".join(item["flags"])})
    return all_rows,pics

def run():
    import torch
    from hydra import initialize_config_dir
    from hydra.core.global_hydra import GlobalHydra
    from sam2.build_sam import build_sam2_video_predictor
    yu,old,hold_hash=validate()
    if not torch.cuda.is_available():raise RuntimeError("CUDA unavailable")
    stage=pathlib.Path(tempfile.mkdtemp(prefix=".threezone_892_",dir=str(ROOT)))
    try:
        fwd,rev=extract(stage)
        GlobalHydra.instance().clear()
        initialize_config_dir(version_base="1.2",config_dir=str(CONF.resolve(strict=True)))
        with torch.inference_mode():
            predictor=build_sam2_video_predictor("sam2.1/sam2.1_hiera_t.yaml",
                                str(MODEL),device="cuda",apply_postprocessing=False)
            print("Tracking cigarette 360 -> 419",flush=True)
            cigstat=follow(predictor,fwd,CIG,False,stage/"cigar_masks")
            print("Tracking hand 419 -> 360",flush=True)
            hstat=follow(predictor,rev,HAND,True,stage/"hand_masks")
            del predictor
        rows,pictures=visualize(stage,fwd,cigstat,hstat,yu,old)
        if sha(SRC)!=SRC_SHA or sha(HOLD)!=hold_hash:
            raise RuntimeError("Source/quarantine changed during test")
        report={"schema":"RG_892_THREEZONE_CIGAR_HAND_MOUTH_SHADOW_V1",
                "created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "frames_total":COUNT,"source_frames":[FIRST,FIRST+COUNT-1],
                "source_sha256":SRC_SHA,"checkpoint_sha256":MODEL_SHA,
                "mouth_yunet_report_reused":True,
                "sam2_hand_and_cigarette_masks_recomputed":True,
                "hand_contact_is_geometry_not_finger_identity":True,
                "mouth_is_landmark_guide_not_lip_segmentation":True,
                "smoke_detector_verified":False,
                "negative_8865_full_video_test_passed":False,
                "three_zone_visual_qa_completed":False,
                "four_zone_blur_verified":False,
                "studio_modified":False,"premiere_xml_modified":False,
                "source_video_modified":False,"source_audio_modified":False,
                "quarantine_886_5_unchanged":True,"production_release_allowed":False,
                "frames":rows}
        (stage/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        zipname="RG_892_THREEZONE_FUSION_SHADOW_V1.zip"
        with zipfile.ZipFile(stage/zipname,"w",zipfile.ZIP_DEFLATED,compresslevel=5) as z:
            for p in ("report.json","metrics.csv","THREEZONE_892_UNAPPROVED_2S_NO_AUDIO.mp4",*pictures):
                z.write(stage/p,p)
            for folder in ("cigar_masks","hand_masks"):
                for p in sorted((stage/folder).glob("*.png")):
                    z.write(p,str(pathlib.Path(folder)/p.name))
        with zipfile.ZipFile(stage/zipname) as z:
            if z.testzip() is not None:raise RuntimeError("ZIP CRC failed")
        OUT.mkdir()
        shutil.move(str(stage/zipname),str(OUT/zipname))
        shutil.move(str(stage/"report.json"),str(OUT/"report.json"))
        print(json.dumps({"status":"THREEZONE_SHADOW_QA_READY","frames":COUNT,
                          "result_zip":str(OUT/zipname),
                          "production_release_allowed":False},indent=2),flush=True)
    finally:
        if stage.exists():shutil.rmtree(stage,ignore_errors=True)

if __name__=="__main__":
    try:
        parser=argparse.ArgumentParser()
        mode=parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--self-test",action="store_true")
        mode.add_argument("--run",action="store_true")
        args=parser.parse_args()
        if args.self_test:test()
        else:run()
    except Exception as exc:
        print("RG_892_THREEZONE_SHADOW_STOPPED: "+str(exc),flush=True)
        sys.exit(2)
