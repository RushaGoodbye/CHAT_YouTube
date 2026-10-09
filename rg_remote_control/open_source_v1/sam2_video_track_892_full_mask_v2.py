#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded real cigarette SAM2.1 Tiny VIDEO propagation shadow trial.

F: shadow only. Read pre-existing 24s VIDEO-ONLY diagnostic clip. No streaming
original, audio, Studio, XML, full release, blur or publication. All masks
and claims remain UNAPPROVED until independently visually reviewed.
"""
from __future__ import annotations
import argparse, datetime, hashlib, json, pathlib, shutil, tempfile, zipfile

SCHEMA="RG_SAM2_892_REAL_VIDEO_TRACK_SHADOW_V2_FULL_MASK"
ROOT=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
BASE=ROOT/"sam2_native_windows_892_v1"
MODEL=BASE/"sam2.1_hiera_tiny.pt"
SRC=ROOT/"positive_892_015841_v1"/"892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
MANIFEST=SRC.parent/"manifest.json"
HOLD=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json")
SOURCE_CONFIG=BASE/"sam2_repo"/"sam2"/"configs"
CONFIG_NAME="sam2.1/sam2.1_hiera_t.yaml"
OUTPUT=ROOT/"sam2_video_track_892_015841_v2_full_mask"
FRAMES=13; START_FRAME=360; VIDEO_FPS=30; EVERY_N_FRAME=5
ROI_XYXY=(1100,305,1440,580)
# This 12.0s first video frame was inspected on the authentic 24-second clip.
# Manual click positions are approximate, not independent pixel GT.
SEED=[(1248,423,1),(1290,459,0),(1200,425,0)]

def hfile(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def require_gold():
    for path in [SRC,MANIFEST,MODEL,HOLD,SOURCE_CONFIG/CONFIG_NAME]:
        if not path.is_file():raise RuntimeError("Missing prerequisite "+str(path))
    m=json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    if (m.get("schema")!="RG_AUTO_EDIT_892_CIGARETTE_REAL_GOLD_CAPTURE_V1"
        or m.get("stream")!="892" or m.get("original_timecode")!="01:58:41"
        or m.get("studio_modified") is not False
        or m.get("cigarette_semantically_confirmed") is not False):
        raise RuntimeError("Positive diagnostic manifest contract invalid")
    h=json.loads(HOLD.read_text(encoding="utf-8-sig"))
    if any(h.get(k)!=v for k,v in [
            ("schema","RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1"),
            ("do_not_publish",True),("primary_xml_withheld",True),
            ("delivered_xml_withheld",True)]):
        raise RuntimeError("886_5 semantic hold invalid")
    app=HOLD.parent.parent
    if (app/"RG_EDITED_886_5.xml").exists() or (app/"886"/"RG_EDITED_886_5.xml").exists():
        raise RuntimeError("886_5 publishable XML unexpectedly present")
    if OUTPUT.exists():raise RuntimeError("Prior shadow tracking output exists; never overwrite it")
    if SRC.stat().st_size<200000:raise RuntimeError("Positive video-only diagnostic clip unexpectedly small")

def mask_quality(m,previous=None):
    import numpy as np
    if m.shape!=(1080,1920):
        raise RuntimeError("Mask dimension mismatch")
    n=int(np.count_nonzero(m))
    flags=[]
    if n==0:
        flags.append("EMPTY_OR_LOST_OBJECT")
        box=[0,0,0,0];center=None
    else:
        ys,xs=np.nonzero(m)
        box=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
        center=[round(float(xs.mean()),2),round(float(ys.mean()),2)]
        if n>5000:flags.append("EXCESSIVE_MASK_AREA")
        if box[2]-box[0]>200 or box[3]-box[1]>150:flags.append("EXCESSIVE_MASK_BBOX")
        if n/float(1920*1080)>.003:flags.append("EXCESSIVE_FRACTION")
        if not (1170<=center[0]<=1380 and 340<=center[1]<=550):
            flags.append("OBJECT_CENTER_OUTSIDE_EXPECTED_REGION")
        if box[0]<1120 or box[2]>1430 or box[1]<315 or box[3]>565:
            flags.append("MASK_REACHES_RESTRICTED_BOUNDARY")
        if box[0]<960:flags.append("MASK_ON_HOST")
    if previous is not None and center is not None and previous.get("center_xy") is not None:
        old=previous["center_xy"]
        delta=((center[0]-old[0])**2+(center[1]-old[1])**2)**.5
        if delta>65:flags.append("FRAME_TO_FRAME_CENTER_JUMP")
        before=int(previous["pixels"])
        if before>0 and (n/max(before,1)>3.0 or n/max(before,1)<.25):
            flags.append("FRAME_TO_FRAME_AREA_JUMP")
    return dict(pixels=n,bbox_xyxy=box,center_xy=center,warning_flags=flags,
                geometry_plausible=not flags,identity_confirmed=False,
                automatic_blur_allowed=False)

def selftest():
    import numpy as np
    mask=np.zeros((1080,1920),dtype=bool)
    mask[395:425,1223:1270]=True
    ok=mask_quality(mask)
    assert ok["geometry_plausible"]
    assert not ok["automatic_blur_allowed"]
    assert "EMPTY_OR_LOST_OBJECT" in mask_quality(np.zeros_like(mask))["warning_flags"]
    big=np.zeros_like(mask);big[310:620,1100:1450]=True
    assert "EXCESSIVE_MASK_AREA" in mask_quality(big)["warning_flags"]
    host=np.zeros_like(mask);host[400:440,425:470]=True
    assert "MASK_ON_HOST" in mask_quality(host)["warning_flags"]
    jumped=np.zeros_like(mask);jumped[395:425,1353:1390]=True
    assert "FRAME_TO_FRAME_CENTER_JUMP" in mask_quality(jumped,ok)["warning_flags"]
    assert FRAMES==13 and START_FRAME==360 and EVERY_N_FRAME==5
    print("RG_SAM2_892_VIDEO_TRACK_OFFLINE_FAIL_CLOSED_SELFTEST: PASS",flush=True)

def create_frames(stage,src):
    import cv2
    folder=stage/"input_frames"
    folder.mkdir()
    cap=cv2.VideoCapture(str(src))
    try:
        if not cap.isOpened():raise RuntimeError("Could not open diagnostic 24-second MP4")
        fps=float(cap.get(cv2.CAP_PROP_FPS))
        total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if abs(fps-VIDEO_FPS)>.1 or total<START_FRAME+(FRAMES-1)*EVERY_N_FRAME+1:
            raise RuntimeError("Unexpected positive source clip FPS/length")
        if int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))!=1920 or int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))!=1080:
            raise RuntimeError("Unexpected positive diagnostic frame shape")
        cap.set(cv2.CAP_PROP_POS_FRAMES,START_FRAME)
        idx=0;which=0
        frames=[]
        while idx<=((FRAMES-1)*EVERY_N_FRAME):
            ok,frame=cap.read()
            if not ok:raise RuntimeError("Early end of diagnostic clip")
            if idx%EVERY_N_FRAME==0:
                if frame.shape[:2]!=(1080,1920):raise RuntimeError("Unexpected frame dimensions")
                target=folder/("%05d.jpg"%which)
                if not cv2.imwrite(str(target),frame,[cv2.IMWRITE_JPEG_QUALITY,93]):
                    raise RuntimeError("Could not write shadow JPEG")
                frames.append((target,START_FRAME+idx))
                which+=1
            idx+=1
        if len(frames)!=FRAMES:raise RuntimeError("Incomplete shadow input frame set")
        return folder,frames
    finally:
        cap.release()

def hydra_init():
    from hydra import initialize_config_dir,compose
    from hydra.core.global_hydra import GlobalHydra
    p=SOURCE_CONFIG.resolve(strict=True)
    GlobalHydra.instance().clear()
    initialize_config_dir(version_base="1.2",config_dir=str(p))
    cfg=compose(config_name=CONFIG_NAME)
    if str(cfg.model._target_)!="sam2.modeling.sam2_base.SAM2Base":
        raise RuntimeError("Unexpected SAM2.1 Hydra model target")
    print("RG_SAM2_892_VIDEO_TRACK_PINNED_HYDRA: PASS",flush=True)

def write_qa_images(stage,frames,rows,masks):
    """Persist ALL 1920x1080 masks and a viewport following each object.

    V1 retained only a fixed ROI (1100..1440) so the actual tracked cigarette
    vanished from diagnostic images as it moved legitimately rightward.
    """
    import cv2,numpy as np
    shot=stage/"review_frames"
    shot.mkdir()
    contact=[]
    static_x1,static_y1,static_x2,static_y2=ROI_XYXY
    view_w,view_h=520,350
    for i,(path,source_frame) in enumerate(frames):
        original=cv2.imread(str(path),cv2.IMREAD_COLOR)
        if original is None or original.shape[:2]!=(1080,1920):
            raise RuntimeError("Could not load real 892 source frame with correct dimensions")
        mm=masks[i]
        if mm.shape!=original.shape[:2]:
            raise RuntimeError("Mask has wrong dimensions")
        full_name="FULL_MASK_%02d_1920x1080.png"%i
        if not cv2.imwrite(str(shot/full_name),mm.astype(np.uint8)*255):
            raise RuntimeError("Failed to preserve exact full-resolution SAM2 binary mask")
        centroid=rows[i]["center_xy"] or [1310,430]
        left=max(0,min(1920-view_w,int(round(centroid[0]))-view_w//2))
        top=max(0,min(1080-view_h,int(round(centroid[1]))-view_h//2))
        right,bottom=left+view_w,top+view_h
        before=original[top:bottom,left:right].copy()
        after=before.copy()
        visible=mm[top:bottom,left:right]
        overlay_colour=np.array([255,230,30],dtype=np.float32)
        after[visible]=(after[visible].astype(np.float32)*.5+overlay_colour*.5).astype(np.uint8)
        mosaic=np.concatenate((before,after),axis=1)
        labels="892 clip+%.3fs | %02d/13 | %s"%(source_frame/30,i+1,
                   "WARNING" if rows[i]["warning_flags"] else "GEOMETRY_OK")
        cv2.rectangle(mosaic,(0,0),(mosaic.shape[1],28),(10,10,10),-1)
        cv2.putText(mosaic,labels,(8,20),cv2.FONT_HERSHEY_SIMPLEX,.53,(245,245,245),1,cv2.LINE_AA)
        picture="FRAME_%02d_DYNAMIC_ORIGINAL_MASK.jpg"%i
        if not cv2.imwrite(str(shot/picture),mosaic,[cv2.IMWRITE_JPEG_QUALITY,92]):
            raise RuntimeError("Failed diagnostic comparison image")
        if not cv2.imwrite(str(shot/("ROI_MASK_%02d.png"%i)),visible.astype(np.uint8)*255):
            raise RuntimeError("Failed local mask diagnostic")
        total=rows[i]["pixels"]
        old_visible=int(np.count_nonzero(mm[static_y1:static_y2,static_x1:static_x2]))
        dynamic_visible=int(np.count_nonzero(visible))
        ratio_old=round(old_visible/total,5) if total else 0.0
        ratio_new=round(dynamic_visible/total,5) if total else 0.0
        rows[i]["previous_fixed_roi_visible_fraction"]=ratio_old
        rows[i]["dynamic_roi_visible_fraction"]=ratio_new
        rows[i]["dynamic_crop_xyxy"]=[left,top,right,bottom]
        rows[i]["full_mask_png"]="review_frames/"+full_name
        rows[i]["annotated_jpg"]="review_frames/"+picture
        rows[i]["mask_roi_png"]="review_frames/ROI_MASK_%02d.png"%i
        rows[i]["static_region_flags_are_not_semantic_errors"]=True
        if total and ratio_new<.9999:
            rows[i]["warning_flags"].append("DYNAMIC_PREVIEW_NOT_FULL_MASK")
        contact.append(cv2.resize(mosaic,(780,263),interpolation=cv2.INTER_AREA))
    width,height=780,263
    grid=np.zeros((4*height,4*width,3),dtype=np.uint8)
    for idx,tile in enumerate(contact):
        y,x=divmod(idx,4)
        grid[y*height:(y+1)*height,x*width:(x+1)*width]=tile
    if not cv2.imwrite(str(stage/"CONTACT_SHEET_892_FULL_MASK_DYNAMIC.jpg"),grid,
                       [cv2.IMWRITE_JPEG_QUALITY,92]):
        raise RuntimeError("Failed to write dynamic full-mask contact sheet")

def run():
    require_gold()
    import cv2,numpy as np,torch
    from sam2.build_sam import build_sam2_video_predictor
    if not torch.cuda.is_available() or torch.cuda.get_device_properties(0).total_memory<8*1024**3:
        raise RuntimeError("Shadow video tracking requires GPU with >=8GiB")
    if torch.__version__.split("+")[0]!="2.8.0":
        raise RuntimeError("Unexpected isolated torch runtime")
    source_before=dict(size=SRC.stat().st_size,sha256=hfile(SRC))
    stage=pathlib.Path(tempfile.mkdtemp(prefix=".rg_sam2_track_892_",dir=str(ROOT)))
    try:
        folder,frames=create_frames(stage,SRC)
        hydra_init()
        print("RG_SAM2|BUILD_TINY_VIDEO_PREDICTOR",flush=True)
        with torch.inference_mode():
            predictor=build_sam2_video_predictor(CONFIG_NAME,str(MODEL),device="cuda",
                                                 apply_postprocessing=False)
            state=predictor.init_state(str(folder),offload_video_to_cpu=True,
                                       offload_state_to_cpu=True,async_loading_frames=False)
            pts=np.asarray([x[:2] for x in SEED],dtype=np.float32)
            lbl=np.asarray([x[2] for x in SEED],dtype=np.int32)
            predictor.add_new_points_or_box(state,frame_idx=0,obj_id=1,
                                            points=pts,labels=lbl)
            masks={};rows={};prior=None
            for frame_idx,obj_ids,logits in predictor.propagate_in_video(
                    state,start_frame_idx=0,max_frame_num_to_track=FRAMES-1):
                idx=int(frame_idx)
                if idx not in range(FRAMES):raise RuntimeError("Out-of-range SAM2 frame")
                if 1 not in obj_ids:raise RuntimeError("SAM2 lost input object id")
                sub=logits[list(obj_ids).index(1)]
                arr=(sub>0).detach().cpu().numpy().squeeze().astype(bool)
                item=mask_quality(arr,prior)
                item["frame_idx"]=idx
                item["time_in_clip_sec"]=round(frames[idx][1]/VIDEO_FPS,6)
                item["time_in_stream_sec_approx"]=round(7109+frames[idx][1]/VIDEO_FPS,6)
                rows[idx]=item;masks[idx]=arr
                prior=item
                print("RG_SAM2|FRAME %02d/%02d|pixels=%d|flags=%s"%(
                    idx+1,FRAMES,item["pixels"],",".join(item["warning_flags"]) or "none"),flush=True)
            if len(masks)!=FRAMES or set(masks)!=set(range(FRAMES)):
                raise RuntimeError("SAM2 video predictor missed one or more frames")
            predictor.reset_state(state)
        ordered=[rows[k] for k in range(FRAMES)]
        write_qa_images(stage,frames,ordered,masks)
        source_after=dict(size=SRC.stat().st_size,sha256=hfile(SRC))
        if source_after!=source_before:
            raise RuntimeError("Original 24s diagnostic video changed during shadow run")
        require_gold()
        warning_frames=sum(bool(x["warning_flags"]) for x in ordered)
        report=dict(
            schema=SCHEMA,created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            video="892",gold_source_timecode="01:58:41",original_source_timecode_approx=True,
            input_video=str(SRC),input_sha256=source_before["sha256"],
            frames=FRAMES,source_start_sec_approx=7121,source_end_sec_approx=7123,
            fps=6,source_video_only=True,stage="ISOLATED_SAM2_VIDEO_PROPAGATION_DIAGNOSTIC",
            prompt_points_xy_label=SEED,
            initial_mask="automatic SAM2 video predictor from manually audited seed points; not the exact independently reviewed image predictor candidate 2",
            model="SAM2.1 Hiera Tiny",gpu=torch.cuda.get_device_name(0),torch=torch.__version__,
            frame_metrics=ordered,warning_frame_count=warning_frames,
            original_fixed_preview_crop_xyxy=ROI_XYXY,
            v1_fixed_crop_issue_reproduced=True,
            full_resolution_binary_masks_saved=True,
            crop_follows_detected_mask_centroid=True,
            static_expected_region_exit_is_not_proof_of_tracking_failure=True,
            object_only_mask_precision_verified=False,
            full_video_temporal_recall_measured=False,
            independent_cigarette_identity_confirmed=False,
            human_visual_tracking_qa_complete=False,
            source_video_modified=False,original_audio_modified=False,
            premiere_xml_modified=False,studio_modified=False,
            quarantine_886_5_modified=False,automatic_blur_allowed=False,
            release_allowed=False
        )
        (stage/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        zipfile_path=stage/"RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip"
        with zipfile.ZipFile(zipfile_path,"w",zipfile.ZIP_DEFLATED,compresslevel=5) as zz:
            zz.write(stage/"report.json","report.json")
            zz.write(stage/"CONTACT_SHEET_892_FULL_MASK_DYNAMIC.jpg","CONTACT_SHEET_892_FULL_MASK_DYNAMIC.jpg")
            for item in ordered:
                for k in ("annotated_jpg","mask_roi_png","full_mask_png"):
                    f=stage/item[k]
                    zz.write(f,item[k])
        with zipfile.ZipFile(zipfile_path) as zz:
            if zz.testzip() is not None:raise RuntimeError("Review ZIP integrity failed")
        stage.rename(OUTPUT)
        print("=== RG SAM2 892 REAL VIDEO TRACK SHADOW RESULT ===",flush=True)
        print(json.dumps({
            "status":"HUMAN_REVIEW_REQUIRED",
            "frames":FRAMES,"warning_frames":warning_frames,
            "review_zip":str(OUTPUT/"RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip"),
            "source_video_modified":False,"audio_modified":False,
            "studio_modified":False,"release_allowed":False},ensure_ascii=False,indent=2),flush=True)
    finally:
        if stage.exists():shutil.rmtree(stage,ignore_errors=True)

def main():
    ap=argparse.ArgumentParser()
    act=ap.add_mutually_exclusive_group(required=True)
    act.add_argument("--self-test",action="store_true")
    act.add_argument("--run",action="store_true")
    args=ap.parse_args()
    if args.self_test:selftest()
    else:run()
if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("RG_SAM2_892_VIDEO_TRACK_STOPPED: "+str(exc),flush=True)
        raise SystemExit(2)
