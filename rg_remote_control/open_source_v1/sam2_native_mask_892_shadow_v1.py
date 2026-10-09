#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One genuine cigarette frame SAM 2.1 image mask trial, never a blur/release."""
from __future__ import annotations
import argparse, hashlib, json, pathlib, tempfile, datetime, shutil
VERSION="RG_SAM2_892_IMAGE_MASK_SHADOW_V1"
ROOT=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
FRAME=ROOT/"positive_892_015841_v1"/"keyframes"/"892_CIGARETTE_POTENTIAL_049.jpg"
MODEL=ROOT/"sam2_native_windows_892_v1"/"sam2.1_hiera_tiny.pt"
OUTPUT=ROOT/"sam2_native_windows_892_v1"/"review"
# Experimental user-video coordinates, not verified per-pixel training labels.
SEED=[(1248,423,1),(1290,459,0),(1200,425,0)]

def evaluate(mask,h,w):
    import numpy as np
    x=np.asarray(mask,dtype=bool)
    if x.shape!=(h,w):raise RuntimeError("Invalid candidate mask dimensions")
    n=int(x.sum())
    if n:
        ys,xs=np.where(x)
        box=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
        cx=float(xs.mean());cy=float(ys.mean())
    else:box=[0,0,0,0];cx=cy=0
    reasons=[]
    if n==0:reasons.append("EMPTY_MASK")
    if n>5000:reasons.append("TOO_LARGE_FOR_CIGARETTE")
    if n/(h*w)>.003:reasons.append("MASK_OVERSIZE_FRACTION")
    if box[2]-box[0]>200 or box[3]-box[1]>150:reasons.append("MASK_BOX_TOO_LARGE")
    if n and cx<w/2:reasons.append("MASK_LEAKS_TO_HOST")
    if n and not (1170<=cx<=1340 and 345<=cy<=525):reasons.append("MASK_CENTER_OUTSIDE_GUEST_CIGARETTE")
    return dict(pixels=n,bbox_xyxy=box,center_xy=[round(cx,1),round(cy,1)],
                suspicious_geometry=reasons,geometry_ok=not reasons,
                visual_identity_verified=False,automatic_blur_allowed=False)

def selftest():
    import numpy as np
    h,w=1080,1920
    tiny=np.zeros((h,w),dtype=bool);tiny[403:431,1215:1263]=1
    big=np.zeros((h,w),dtype=bool);big[220:480,1100:1440]=1
    host=np.zeros((h,w),dtype=bool);host[400:450,450:520]=1
    assert evaluate(tiny,h,w)["geometry_ok"]
    assert not evaluate(tiny,h,w)["automatic_blur_allowed"]
    assert "TOO_LARGE_FOR_CIGARETTE" in evaluate(big,h,w)["suspicious_geometry"]
    assert "MASK_LEAKS_TO_HOST" in evaluate(host,h,w)["suspicious_geometry"]
    assert "EMPTY_MASK" in evaluate(np.zeros((h,w),dtype=bool),h,w)["suspicious_geometry"]
    assert not OUTPUT.exists() or OUTPUT.is_dir()
    print("RG_SAM2_NATIVE_ONE_FRAME_MASK_QA_SELFTEST: PASS",flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--run",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        selftest();return
    if not args.run:raise RuntimeError("Only --self-test or --run allowed")
    import cv2, numpy as np, torch
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    if not torch.cuda.is_available():raise RuntimeError("Independent shadow CUDA unavailable")
    if torch.__version__.split("+")[0]!="2.8.0":raise RuntimeError("Unexpected independent torch version")
    if not FRAME.is_file() or not MODEL.is_file():raise RuntimeError("Positive gold JPG or model checkpoint unavailable")
    im=cv2.imread(str(FRAME),cv2.IMREAD_COLOR)
    if im is None or im.shape[:2]!=(1080,1920):raise RuntimeError("Gold JPEG wrong resolution")
    if OUTPUT.exists():raise RuntimeError("Existing mask review dir - refuse overwrite")
    print("RG_SAM2|DEVICE="+torch.cuda.get_device_name(0),flush=True)
    model=build_sam2("configs/sam2.1/sam2.1_hiera_t.yaml",str(MODEL),
                     device="cuda",apply_postprocessing=False)
    pred=SAM2ImagePredictor(model)
    with torch.inference_mode():
        pred.set_image(cv2.cvtColor(im,cv2.COLOR_BGR2RGB))
        masks,scores,_=pred.predict(
            point_coords=np.asarray([r[:2] for r in SEED],dtype=np.float32),
            point_labels=np.asarray([r[2] for r in SEED],dtype=np.int32),
            multimask_output=True)
    if len(masks)==0:raise RuntimeError("No SAM2 mask candidates")
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    stage=pathlib.Path(tempfile.mkdtemp(prefix=".sam2_892_",dir=str(OUTPUT.parent)))
    try:
        results=[]
        for i,(mask,score) in enumerate(zip(masks,scores),1):
            m=np.asarray(mask,dtype=bool)
            row=evaluate(m,im.shape[0],im.shape[1])
            row.update(candidate=i,sam2_score=float(score))
            out=im.copy()
            colour=np.asarray([255,255,0],dtype=np.float32)
            out[m]=np.clip(out[m].astype(np.float32)*.5+colour*.5,0,255).astype(np.uint8)
            for px,py,is_positive in SEED:
                cv2.circle(out,(px,py),7,(0,230,0) if is_positive else (0,0,255),2)
            filename="SAM2_892_CANDIDATE_%d.jpg"%i
            if not cv2.imwrite(str(stage/filename),out,[cv2.IMWRITE_JPEG_QUALITY,94]):
                raise RuntimeError("Failed writing diagnostic JPG")
            row["annotated_jpg"]=filename
            results.append(row)
        report=dict(
            schema=VERSION,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            positive_stream="892",positive_timecode="01:58:41",
            original_video_source_jpg=str(FRAME),original_jpg_sha256=hashlib.sha256(FRAME.read_bytes()).hexdigest(),
            checkpoint_sha256=hashlib.sha256(MODEL.read_bytes()).hexdigest(),
            gpu=torch.cuda.get_device_name(0),torch=torch.__version__,
            model="sam2.1_hiera_tiny",seed_points_xy_label=SEED,
            candidates=results,independent_cigarette_classification_performed=False,
            moving_cigarette_tracking_verified=False,human_visual_mask_qa_complete=False,
            studio_modified=False,original_audio_modified=False,source_video_modified=False,
            premiere_xml_modified=False,quarantine_886_5_modified=False,
            automatic_blur_allowed=False,release_allowed=False)
        (stage/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        stage.rename(OUTPUT)
    finally:
        if stage.exists():shutil.rmtree(stage,ignore_errors=True)
    print("=== RG SAM2 892 REAL CIGARETTE ONE-FRAME MASK REVIEW ===",flush=True)
    print(json.dumps({"status":"VISUAL_REVIEW_REQUIRED","mask_candidates":len(results),
                      "report":str(OUTPUT/"report.json"),"output_dir":str(OUTPUT),
                      "production_modified":False,"auto_blur_allowed":False},ensure_ascii=False,indent=2),flush=True)
if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("RG SAM2 NATIVE SHADOW STOPPED, STUDIO UNCHANGED: "+str(exc),flush=True)
        raise SystemExit(2)
