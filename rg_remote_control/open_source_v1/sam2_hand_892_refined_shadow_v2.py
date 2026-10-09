#!/usr/bin/env python3
"""892 hand prompt refinement, isolated image SAM2 candidate QA. NO BLUR/RELEASE."""
import pathlib,hashlib,json,datetime,zipfile,sys
ROOT=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
SRC=ROOT/"positive_892_015841_v1"/"892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
MODEL=ROOT/"sam2_native_windows_892_v1"/"sam2.1_hiera_tiny.pt"
CONF=ROOT/"sam2_native_windows_892_v1"/"sam2_repo"/"sam2"/"configs"
HOLD=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json")
OUT=ROOT/"sam2_hand_892_frame419_refined_shadow_v2"
SRC_SHA="bf2e3e585afeaa0b0ba3c347066a6ca1adcacfec282cba691cc7ec9d1ae3b49c"
MODEL_SHA="7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
BASE=[(1305,635,1),(1365,595,1),(1413,534,1),(1475,489,0),(1558,500,0),(1160,460,0)]
# These are unvalidated manual candidate prompts, NOT verified finger landmarks.
PROMPTS={
 "baseline":BASE,
 "fingertip_a":BASE+[(1392,500,1),(1431,478,1),(1495,437,0),(1515,562,0)],
 "fingertip_b":BASE+[(1373,524,1),(1409,491,1),(1446,485,1),(1470,406,0),(1512,515,0)]
}
def sha(path):
 h=hashlib.sha256()
 with open(path,"rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 return h.hexdigest()
def main():
 import cv2,numpy as np,torch
 from hydra import initialize_config_dir
 from hydra.core.global_hydra import GlobalHydra
 from sam2.build_sam import build_sam2
 from sam2.sam2_image_predictor import SAM2ImagePredictor
 for p in (SRC,MODEL,HOLD,CONF/"sam2.1/sam2.1_hiera_t.yaml"):
  if not p.is_file():raise RuntimeError("Missing immutable input: "+str(p))
 if sha(SRC)!=SRC_SHA or sha(MODEL)!=MODEL_SHA:raise RuntimeError("Pinned source/model SHA mismatch")
 q=json.loads(HOLD.read_text(encoding="utf-8-sig"))
 for k,v in (("schema","RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1"),("do_not_publish",True),("primary_xml_withheld",True),("delivered_xml_withheld",True)):
  if q.get(k)!=v:raise RuntimeError("886_5 quarantine invalid: "+k)
 if OUT.exists():raise RuntimeError("Result folder already exists; do not overwrite")
 if not torch.cuda.is_available():raise RuntimeError("CUDA unavailable")
 cap=cv2.VideoCapture(str(SRC));cap.set(cv2.CAP_PROP_POS_FRAMES,419)
 ok,im=cap.read();cap.release()
 if not ok or im.shape[:2]!=(1080,1920):raise RuntimeError("Frame 419 unavailable")
 GlobalHydra.instance().clear();initialize_config_dir(version_base="1.2",config_dir=str(CONF.resolve(strict=True)))
 with torch.inference_mode():
  model=build_sam2("sam2.1/sam2.1_hiera_t.yaml",str(MODEL),device="cuda",apply_postprocessing=False)
  predictor=SAM2ImagePredictor(model)
  predictor.set_image(cv2.cvtColor(im,cv2.COLOR_BGR2RGB))
  predictions=[]
  for label,pts in PROMPTS.items():
   mm,scores,_=predictor.predict(point_coords=np.array([p[:2] for p in pts],np.float32),point_labels=np.array([p[2] for p in pts],np.int32),multimask_output=True)
   for j,(m,s) in enumerate(zip(mm,scores),1):
    predictions.append((label,pts,j,np.asarray(m,dtype=bool),float(s)))
 OUT.mkdir(parents=True)
 rows=[]
 for label,pts,j,m,s in predictions:
  ys,xs=np.nonzero(m);area=int(m.sum())
  bbox=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)] if area else None
  rgb=im.copy();rgb[m]=(rgb[m].astype(np.float32)*.53+np.array([245,80,155],np.float32)*.47).astype(np.uint8)
  for x,y,pos in pts:cv2.circle(rgb,(x,y),7,(0,255,0) if pos else (0,0,255),2)
  name=f"{label}_{j}.jpg";maskname=f"{label}_{j}_mask.png"
  if not cv2.imwrite(str(OUT/name),rgb[300:850,1100:1650]):raise RuntimeError("Failed JPG write")
  if not cv2.imwrite(str(OUT/maskname),(m[300:850,1100:1650].astype("uint8")*255)):raise RuntimeError("Failed mask write")
  rows.append(dict(image=name,mask=maskname,seed_set=label,index=j,score=s,area=area,bbox_xyxy=bbox,hand_identity_verified=False,finger_contact_verified=False))
 report=dict(schema="RG_892_HAND_SAM2_REFINED_SHADOW_V2",created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_frame=419,source_sha256=SRC_SHA,checkpoint_sha256=MODEL_SHA,prompts=PROMPTS,candidates=rows,release_allowed=False,studio_modified=False,premiere_xml_modified=False,original_video_modified=False,original_audio_modified=False,quarantine_886_5_unchanged=True,notes="SAM2 confidence does not prove fingertip coverage; visually review original and masks")
 (OUT/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
 with zipfile.ZipFile(OUT/"RG_892_HAND_SAM2_REFINED_SHADOW_V2.zip","w",zipfile.ZIP_DEFLATED) as z:
  z.write(OUT/"report.json","report.json")
  for r in rows:
   for k in ("image","mask"):z.write(OUT/r[k],r[k])
 with zipfile.ZipFile(OUT/"RG_892_HAND_SAM2_REFINED_SHADOW_V2.zip") as z:
  if z.testzip() is not None:raise RuntimeError("ZIP CRC failed")
 if sha(SRC)!=SRC_SHA:raise RuntimeError("Original source changed")
 print(json.dumps(dict(status="VISUAL_QA_REQUIRED",candidate_count=len(rows),result_zip=str(OUT/"RG_892_HAND_SAM2_REFINED_SHADOW_V2.zip"),release_allowed=False),indent=2))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("RG_HAND_REFINED_SHADOW_STOPPED: "+str(e),flush=True);sys.exit(2)
