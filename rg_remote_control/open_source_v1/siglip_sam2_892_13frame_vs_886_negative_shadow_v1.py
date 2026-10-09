#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real 13-frame SAM2 892 vs 3 negative crops independent SigLIP benchmark.

GPU inference read-only in existing separate F: SigLIP shadow environment.
NO pip, model downloads, blur, production changes, XML edits or release.
Raw comparative logits are NOT calibrated cigarette probabilities.
"""
from __future__ import annotations
import argparse, datetime, hashlib, io, json, pathlib, shutil, tempfile, zipfile

SCHEMA="RG_SIGLIP_SAM2_892_THIRTEEN_VS_THREE_REAL_NEGATIVE_SHADOW_V1"
ROOT=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
SOURCE=ROOT/"positive_892_015841_v1"/"892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
TRACK=ROOT/"sam2_video_track_892_015841_v2_full_mask"/"RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip"
NEG=ROOT/"siglip_cigarette_independent_892_886_v1"/"RG_SIGLIP_892_886_CIGARETTE_SHADOW_V1.zip"
HOLD=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json")
OUT=ROOT/"siglip_sam2_892_vs_886_real_13frame_shadow_v1"
MODEL="google/siglip-base-patch16-224"
REV="d0ffe3fe6b24d37e1fc878f6f6c12837e82e8d21"
TRACK_SHA="2d88cf9d763d9c885702a7cc8f254fe9dba75d000de616df5781f28af2e68044"
NEG_SHA="588189bc32cd683a6dce3488eb7816eaa912e34695ae063aed06e3ae52ed4ba8"
SOURCE_SHA="bf2e3e585afeaa0b0ba3c347066a6ca1adcacfec282cba691cc7ec9d1ae3b49c"
N=13
FPS=30
PROMPTS=[
 ("cigarette_lit","A photograph of a lit tobacco cigarette held between fingers, with a visible cigarette tip."),
 ("cigarette_mouth","A photograph of a person smoking a real cigarette near their mouth."),
 ("microphone_logo","A photograph of a black microphone windscreen with a small bright embroidered logo."),
 ("microphone","A photograph of a studio microphone used by a streamer."),
 ("mug","A photograph of a mug or cup a person is drinking from."),
 ("hands","A photograph of hands and fingers without a cigarette."),
 ("smoke_only","A photograph of cigarette smoke without any visible cigarette."),
 ("face","A photograph of a person's face without a cigarette."),
]
NEGATIVES=("NEG_886_MIC_MANUAL","NEG_892_MIC","NEG_892_MUG")

def sha(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def classify(values):
    if len(values)!=len(PROMPTS):raise ValueError("Unexpected independent verifier prompt dimension")
    ranks=sorted(range(len(values)),key=lambda i:float(values[i]),reverse=True)
    positives=(0,1)
    cig=max(float(values[i]) for i in positives)
    other=max(float(values[i]) for i in range(2,len(PROMPTS)))
    margin=round(cig-other,5)
    tag=("CIGARETTE_CANDIDATE" if margin>=.015 else
         "OTHER_OBJECT_CANDIDATE" if margin<=-.020 else
         "AMBIGUOUS_CIGARETTE_MAY_BE_PRESENT")
    return dict(top_prompt=PROMPTS[ranks[0]][0],margin=margin,
                semantic_signal=tag,prompt_logits={k:round(float(v),5)
                for v,(k,_) in zip(values,PROMPTS)},
                action="MANDATORY_VISUAL_AND_INDEPENDENT_REVIEW",
                automatic_blur_allowed=False,may_silently_skip_blur=False,
                cigarette_identity_proved=False)

def guard_preflight():
    if OUT.exists():raise RuntimeError("Review output already exists; do not overwrite")
    for f,digest in ((SOURCE,SOURCE_SHA),(TRACK,TRACK_SHA),(NEG,NEG_SHA)):
        if not f.is_file():raise RuntimeError("Missing pinned input "+str(f))
        if sha(f)!=digest:raise RuntimeError("Pinned input digest changed: "+str(f))
    if not HOLD.is_file():raise RuntimeError("Missing 886_5 quarantine marker")
    h=json.loads(HOLD.read_text(encoding="utf-8-sig"))
    for key,expected in (("schema","RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1"),
                         ("do_not_publish",True),("primary_xml_withheld",True),
                         ("delivered_xml_withheld",True)):
        if h.get(key)!=expected:raise RuntimeError("886_5 HOLD mismatch: "+key)
    app=HOLD.parent.parent
    if (app/"RG_EDITED_886_5.xml").exists() or (app/"886"/"RG_EDITED_886_5.xml").exists():
        raise RuntimeError("886_5 publishable XML unexpectedly present")
    if ROOT.anchor=="" or not ROOT.is_dir():raise RuntimeError("Isolated F: root unavailable")

def get_inputs():
    import cv2,numpy as np
    data=[]
    with zipfile.ZipFile(TRACK) as tz,zipfile.ZipFile(NEG) as nz:
        if tz.testzip() is not None or nz.testzip() is not None:
            raise ValueError("Broken input ZIP")
        info=json.loads(tz.read("report.json"))
        if (info.get("schema")!="RG_SAM2_892_REAL_VIDEO_TRACK_SHADOW_V2_FULL_MASK"
            or info.get("frames")!=N or info.get("automatic_blur_allowed") is not False
            or info.get("release_allowed") is not False):
            raise RuntimeError("Unexpected 13-mask report")
        older=json.loads(nz.read("summary.json"))
        if older.get("schema")!="RG_CIGARETTE_SIGLIP_REAL_PAIR_SHADOW_V1":
            raise RuntimeError("Untrusted five-reference negative controls")
        cap=cv2.VideoCapture(str(SOURCE))
        if not cap.isOpened():raise RuntimeError("Could not decode 892 video-only positive reference")
        try:
            if abs(float(cap.get(cv2.CAP_PROP_FPS))-30)>.1:
                raise RuntimeError("Unexpected video FPS")
            for i in range(N):
                mask_raw=np.frombuffer(tz.read("review_frames/FULL_MASK_%02d_1920x1080.png"%i),np.uint8)
                mask=cv2.imdecode(mask_raw,cv2.IMREAD_GRAYSCALE)
                if mask is None or mask.shape!=(1080,1920):
                    raise RuntimeError("Missing full resolution mask at index "+str(i))
                y,x=np.where(mask>0)
                if not len(x):raise RuntimeError("No cigarette candidate mask to challenge")
                if len(x)!=info["frame_metrics"][i]["pixels"]:
                    raise RuntimeError("Mask area not matching report")
                cap.set(cv2.CAP_PROP_POS_FRAMES,360+i*5)
                ok,im=cap.read()
                if not ok or im.shape[:2]!=(1080,1920):
                    raise RuntimeError("Positive frame unavailable")
                centerx=int(round(float(x.mean())))
                centery=int(round(float(y.mean())))
                # 232x232 context: identical scale to earlier five-reference audit.
                sx=max(0,min(1920-232,centerx-116))
                sy=max(0,min(1080-232,centery-116))
                crop=im[sy:sy+232,sx:sx+232].copy()
                data.append(dict(id="POS_892_TRACK_%02d"%i,
                                 human_label="CIGARETTE_SCENE_NOT_PIXEL_MASK_VERIFIED",
                                 stream="892",frame_index=i,time_clip_sec=round(12+i/6,6),
                                 roi_xyxy=[sx,sy,sx+232,sy+232],image=crop,
                                 mask_pixels=len(x)))
        finally:cap.release()
        for key in NEGATIVES:
            j=cv2.imdecode(np.frombuffer(nz.read("crops/"+key+"_crop.jpg"),np.uint8),cv2.IMREAD_COLOR)
            if j is None:raise RuntimeError("Invalid historical negative crop "+key)
            data.append(dict(id=key,human_label="NOT_CIGARETTE_EXACT_REFERENCE",
                             stream="886" if key.startswith("NEG_886") else "892",
                             image=j,roi_xyxy=None,frame_index=None))
    if len(data)!=N+len(NEGATIVES):raise RuntimeError("Challenge reference count mismatch")
    return data

def make_contact(cv2,rows,stage):
    import numpy as np
    width,height=480,240
    grid=np.zeros((4*height,4*width,3),dtype=np.uint8)
    for i,row in enumerate(rows):
        crop=cv2.imread(str(stage/"crops"/(row["id"]+".jpg")),cv2.IMREAD_COLOR)
        thumb=cv2.resize(crop,(width,height-34),interpolation=cv2.INTER_AREA)
        x,y=i%4,i//4
        tile=grid[y*height:(y+1)*height,x*width:(x+1)*width]
        tile[:height-34]=thumb
        label=row["id"]+" | "+str(row["model"]["margin"])+" | "+row["model"]["semantic_signal"]
        cv2.putText(tile,label[:66],(6,height-12),cv2.FONT_HERSHEY_SIMPLEX,.38,(245,245,245),1,cv2.LINE_AA)
    if not cv2.imwrite(str(stage/"CONTACT_SHEET_16_REAL_REFERENCES.jpg"),grid,
                       [cv2.IMWRITE_JPEG_QUALITY,91]):
        raise RuntimeError("Failed writing evidence overview")

def run():
    guard_preflight()
    import cv2,torch
    from PIL import Image
    from transformers import AutoModel,AutoProcessor
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available in pre-existing separate SigLIP environment")
    print("RG_SIGLIP_892_886|PINNED_LOCAL_MODEL_ONLY",flush=True)
    processor=AutoProcessor.from_pretrained(MODEL,revision=REV,
                                             local_files_only=True,trust_remote_code=False)
    model=AutoModel.from_pretrained(MODEL,revision=REV,use_safetensors=True,
                                    local_files_only=True,trust_remote_code=False).eval().to("cuda")
    examples=get_inputs()
    stage=pathlib.Path(tempfile.mkdtemp(prefix=".rg_siglip_892_13frame_",dir=str(ROOT)))
    try:
        crops=stage/"crops";crops.mkdir()
        results=[]
        for item in examples:
            pic=item.pop("image")
            inputs=processor(
                text=[t for _,t in PROMPTS],
                images=Image.fromarray(cv2.cvtColor(pic,cv2.COLOR_BGR2RGB)),
                return_tensors="pt",padding="max_length")
            with torch.inference_mode():
                v=model(**{k:x.to("cuda") for k,x in inputs.items()}).logits_per_image[0].float().cpu().tolist()
            q=classify(v)
            path=crops/(item["id"]+".jpg")
            if not cv2.imwrite(str(path),pic,[cv2.IMWRITE_JPEG_QUALITY,93]):
                raise RuntimeError("Cannot save independent reference "+item["id"])
            results.append(dict(item,model=q))
            print("RG_SIGLIP_892_886|%s|%s|margin=%.5f"%(item["id"],q["semantic_signal"],q["margin"]),flush=True)
        make_contact(cv2,results,stage)
        guard_preflight() # fail closed: still ensure inputs and HOLD unchanged
        summary=dict(schema=SCHEMA,created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            status="INDEPENDENT_SAM2_ROI_SEMANTIC_SHADOW_REVIEW_REQUIRED",
            model_id=MODEL,model_revision=REV,reference_count=len(results),
            actual_gpu_inference_on_13_mask_centered_frames=True,
            three_real_negative_images_rerun=True,
            true_cigarette_positive_scene_may_contain_hand_or_smoke=True,
            uncalibrated_scores_not_certainty=True,
            pixel_ground_truth_tested=False,
            studio_modified=False,source_video_modified=False,original_audio_modified=False,
            xml_modified=False,quarantine_886_5_modified=False,
            cigarette_only_blur_allowed=False,release_allowed=False,
            samples=results)
        (stage/"report.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf8")
        zpath=stage/"RG_SIGLIP_SAM2_892_13FRAME_VS_886_NEGATIVE_SHADOW_V1.zip"
        with zipfile.ZipFile(zpath,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            z.write(stage/"report.json","report.json")
            z.write(stage/"CONTACT_SHEET_16_REAL_REFERENCES.jpg","CONTACT_SHEET_16_REAL_REFERENCES.jpg")
            for row in results:
                f=crops/(row["id"]+".jpg")
                z.write(f,"crops/"+f.name)
        with zipfile.ZipFile(zpath) as z:
            if z.testzip() is not None:raise RuntimeError("Corrupt result ZIP")
        stage.rename(OUT)
        print("=== RG SIGLIP 892/886 REAL 16-REFERENCE SHADOW RESULT ===",flush=True)
        print(json.dumps({"status":"REVIEW_REQUIRED","samples":len(results),
            "zip":str(OUT/zpath.name),"release_allowed":False,"studio_modified":False},ensure_ascii=False,indent=2),flush=True)
    finally:
        if stage.exists():shutil.rmtree(stage,ignore_errors=True)

def selftest():
    assert N==13 and len(NEGATIVES)==3 and len(PROMPTS)==8
    cigarette=[.1,.16,-.1,-.2,.01,.08,.08,.13]
    hand=[.07,.089,-.04,-.01,.03,.099,.071,.075]
    mic=[-.045,.017,.014,.007,.037,.020,-.008,.055]
    assert classify(cigarette)["semantic_signal"]=="CIGARETTE_CANDIDATE"
    assert classify(hand)["semantic_signal"]=="AMBIGUOUS_CIGARETTE_MAY_BE_PRESENT"
    assert classify(mic)["semantic_signal"]=="OTHER_OBJECT_CANDIDATE"
    for v in (cigarette,hand,mic):
        x=classify(v)
        assert not x["automatic_blur_allowed"] and not x["may_silently_skip_blur"]
    print("RG_SIGLIP_SAM2_892_THIRTEEN_PLUS_THREE_FAIL_CLOSED_SELFTEST: PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--run",action="store_true")
    a=p.parse_args()
    if a.self_test:selftest()
    elif a.run:run()
    else:p.error("--self-test or --run required")
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("RG_SIGLIP_SAM2_SHADOW_STOPPED: "+str(e),flush=True)
        raise SystemExit(2)
