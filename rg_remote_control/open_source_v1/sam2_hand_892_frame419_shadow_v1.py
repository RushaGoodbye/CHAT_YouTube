#!/usr/bin/env python3
# RG 892 SAM2 hand segmentation one frame; diagnostic only, never release.
import hashlib,json,pathlib,sys,datetime
ROOT=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
SRC=ROOT/"positive_892_015841_v1"/"892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
MODEL=ROOT/"sam2_native_windows_892_v1"/"sam2.1_hiera_tiny.pt"
CONF=ROOT/"sam2_native_windows_892_v1"/"sam2_repo"/"sam2"/"configs"
HOLD=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json")
OUT=ROOT/"sam2_hand_892_frame419_shadow_v1"
SEEDS=[(1305,635,1),(1365,595,1),(1413,534,1),(1475,489,0),(1558,500,0),(1160,460,0)]
VIDEO_SHA="bf2e3e585afeaa0b0ba3c347066a6ca1adcacfec282cba691cc7ec9d1ae3b49c"
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for c in iter(lambda:f.read(1048576),b""):h.update(c)
 return h.hexdigest()
def main():
 import cv2,numpy as np,torch
 from hydra import initialize_config_dir
 from hydra.core.global_hydra import GlobalHydra
 from sam2.build_sam import build_sam2
 from sam2.sam2_image_predictor import SAM2ImagePredictor
 assert torch.cuda.is_available(),"CUDA unavailable"
 assert SRC.is_file() and MODEL.is_file() and HOLD.is_file(),"Missing immutable input"
 assert sha(SRC)==VIDEO_SHA,"Source hash mismatch"
 hold=json.loads(HOLD.read_text(encoding="utf-8-sig"))
 for k,v in [("schema","RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1"),("do_not_publish",True),("primary_xml_withheld",True),("delivered_xml_withheld",True)]:
  assert hold.get(k)==v,"Quarantine failed: "+k
 assert not OUT.exists(),"Output exists; will not overwrite"
 cap=cv2.VideoCapture(str(SRC));assert cap.isOpened(),"Bad source video"
 cap.set(cv2.CAP_PROP_POS_FRAMES,419)
 ok,frame=cap.read();cap.release()
 assert ok and frame.shape[:2]==(1080,1920),"Frame 419 unavailable"
 GlobalHydra.instance().clear()
 initialize_config_dir(version_base="1.2",config_dir=str(CONF.resolve(strict=True)))
 with torch.inference_mode():
  model=build_sam2("sam2.1/sam2.1_hiera_t.yaml",str(MODEL),device="cuda",apply_postprocessing=False)
  predictor=SAM2ImagePredictor(model)
  predictor.set_image(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
  masks,scores,_=predictor.predict(point_coords=np.array([p[:2] for p in SEEDS],np.float32),point_labels=np.array([p[2] for p in SEEDS],np.int32),multimask_output=True)
 OUT.mkdir(parents=True)
 rows=[]
 for idx,(mask,score) in enumerate(zip(masks,scores)):
  m=np.asarray(mask,dtype=bool)
  ys,xs=np.where(m);area=int(m.sum())
  box=[int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())] if area else None
  output=frame.copy()
  output[m]=(.55*output[m]+.45*np.array([255,100,40])).astype(np.uint8)
  for x,y,pos in SEEDS:cv2.circle(output,(x,y),8,(0,255,0) if pos else (0,0,255),2)
  clip=output[300:850,1100:1650]
  fn=f"hand_candidate_{idx+1}.jpg"
  assert cv2.imwrite(str(OUT/fn),clip)
  rows.append(dict(name=fn,score=float(score),pixels=area,bbox_xyxy=box,approved=False,hand_identity_verified=False,finger_contact_verified=False))
 report=dict(schema="RG_SAM2_HAND_892_FRAME419_SHADOW_V1",created=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=VIDEO_SHA,checkpoint_sha256=sha(MODEL),source_frame=419,time_sec=419/30,seed_points=SEEDS,candidates=rows,hand_identity_verified=False,finger_contact_verified=False,smoke_verified=False,production_release_allowed=False,studio_modified=False,xml_modified=False,source_video_modified=False,quarantine_886_5_unchanged=True)
 (OUT/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 import zipfile
 with zipfile.ZipFile(OUT/"RG_892_HAND_SAM2_SHADOW_V1.zip","w",zipfile.ZIP_DEFLATED) as z:
  z.write(OUT/"report.json","report.json")
  for r in rows:z.write(OUT/r["name"],r["name"])
 assert sha(SRC)==VIDEO_SHA,"Source unexpectedly changed"
 print(json.dumps(dict(status="SHADOW_REVIEW_REQUIRED",candidates=len(rows),result_zip=str(OUT/"RG_892_HAND_SAM2_SHADOW_V1.zip"),release_allowed=False),indent=2))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print("HAND_SHADOW_FAIL_CLOSED:",str(e))
  sys.exit(2)
