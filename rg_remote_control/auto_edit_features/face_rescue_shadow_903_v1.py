#!/usr/bin/env python3
"""Read-only face detection evidence on 903-2 and 903-5 screenshots.

Never edits media, QA, XML or production modules. No model downloads.
Only reports detection geometry, scores and model availability.
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path

APP = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREENS = Path(r"\\Desktop-v7gg0en\record\Screens")
SHOTS = ("903-2.jpg", "903-5.jpg")

def crop_views(image):
    h, w = image.shape[:2]
    return (
        ("top48", image[:max(24, int(h*.48)), :], 0., 0.),
        ("top70", image[:max(24, int(h*.70)), :], 0., 0.),
        ("right_top70", image[:max(24,int(h*.70)), int(w*.50):], float(int(w*.50)), 0.),
        ("right_top100", image[:,int(w*.50):], float(int(w*.50)), 0.),
    )

def valid_box(box, width, height, min_px=20):
    if not box or len(box)!=4: return False
    if not all(math.isfinite(float(v)) for v in box): return False
    x,y,w,h=map(float,box)
    return (w>=min_px and h>=min_px and x<width and y<height
            and x+w>0 and y+h>0)

def process():
    if not APP.is_dir(): raise RuntimeError("Backend missing")
    sys.path.insert(0,str(APP))
    import cv2
    import numpy as np
    from rg_face_identity import face_candidates_from_image, runtime_info
    from rg_mediapipe_tasks import ensure_model, create_face_landmarker, detect_face_landmarks
    res={"schema":"RG_FACE_RESCUE_SHADOW_903_V1","read_only":True,"download_models":False,
         "auto_release":False,"source_xml_changes":0,"screenshots":{},"sface":runtime_info(),
         "mediapipe":{"available":False}}
    landmarker=None
    try:
        m=ensure_model(allow_download=False,verbose=False)
        res["mediapipe"]={"available":True,"model_exists":bool(m.is_file())}
        landmarker=create_face_landmarker(num_faces=1)
    except Exception as exc:
        res["mediapipe"]={"available":False,"reason":type(exc).__name__}
    for name in SHOTS:
        p=SCREENS/name
        if not p.is_file():
            res["screenshots"][name]={"exists":False}; continue
        raw=np.fromfile(str(p),dtype=np.uint8)
        image=cv2.imdecode(raw,cv2.IMREAD_COLOR)
        if image is None:
            res["screenshots"][name]={"exists":True,"decoded":False};continue
        h,w=image.shape[:2]
        row={"exists":True,"shape":[w,h],"sface":[],"mediapipe":[]}
        for view,roi,dx,dy in crop_views(image):
            for factor,score in ((1,0.48),(2,0.42)):
                try:
                    inp=cv2.resize(roi,None,fx=factor,fy=factor) if factor!=1 else roi
                    faces=face_candidates_from_image(inp,score_threshold=score,min_face_px=20)
                    for f in faces[:4]:
                        x,y,bw,bh=map(float,f["bbox"])
                        box=[round(dx+x/factor,2),round(dy+y/factor,2),
                             round(bw/factor,2),round(bh/factor,2)]
                        if valid_box(box,w,h):
                            row["sface"].append({"view":view,"scale":factor,
                                "score":round(float(f["score"]),3),"box":box,
                                "right":bool(box[0]+box[2]*.5>=.58*w)})
                except Exception as exc:
                    row.setdefault("errors",[]).append("sface:"+type(exc).__name__)
            if landmarker is not None:
                try:
                    rgb=cv2.cvtColor(roi,cv2.COLOR_BGR2RGB)
                    landmarks=detect_face_landmarks(landmarker,rgb)
                    if landmarks:
                        xs=np.array([float(q.x) for q in landmarks],dtype=float)
                        ys=np.array([float(q.y) for q in landmarks],dtype=float)
                        a=max(0.,float(np.quantile(xs,.01)));b=min(1.,float(np.quantile(xs,.99)))
                        c=max(0.,float(np.quantile(ys,.01)));d=min(1.,float(np.quantile(ys,.99)))
                        box=[round(dx+a*roi.shape[1],2),round(dy+c*roi.shape[0],2),
                             round((b-a)*roi.shape[1],2),round((d-c)*roi.shape[0],2)]
                        if valid_box(box,w,h):
                            row["mediapipe"].append({"view":view,"box":box,
                                "right":bool(box[0]+box[2]*.5>=.58*w)})
                except Exception as exc:
                    row.setdefault("errors",[]).append("mediapipe:"+type(exc).__name__)
        res["screenshots"][name]=row
    if landmarker is not None:
        try: landmarker.close()
        except Exception:pass
    return res

if __name__=="__main__":
    print("RG_FACE_RESCUE_SHADOW|"+json.dumps(process(),ensure_ascii=False),flush=True)
