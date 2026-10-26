#!/usr/bin/env python3
"""Read-only bounded search for unresolved 907-3/4; does not alter media or XML."""
import json,sys
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _probe_duration,_iter_window_ffmpeg,_best_local_match
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    video,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not video or not Path(video).is_file():raise RuntimeError("Source unavailable")
    duration=float(_probe_duration(video))
    if not 9000<duration<13000:raise RuntimeError("Unexpected source duration")
    report={}
    for ix in (3,4):
        image=cv2.imread(str(SCREEN/f"907-{ix}.jpg"))
        if image is None:raise RuntimeError(f"Screenshot {ix} missing")
        ref,meta=_reference_guest_descriptor(image)
        if ref is None:
            report[str(ix)]={"reason":"NO_GUEST_REFERENCE","candidates":[]}
            continue
        clusters={}
        count=0
        for sec,frame in _iter_window_ffmpeg(str(video),5500,duration,sample_fps=.35):
            count+=1
            if count>2100:raise RuntimeError("Scan frame budget exceeded")
            state,_,score,_,_=_frame_identity_state(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
            if state=="CURRENT":
                bucket=int(sec//90)
                item=clusters.setdefault(bucket,{"hits":0,"peak":0.,"time":sec})
                item["hits"]+=1
                if float(score)>item["peak"]:item["peak"]=float(score);item["time"]=sec
        best=sorted(clusters.values(),key=lambda z:(z["hits"],z["peak"]),reverse=True)[:10]
        candidates=[]
        for item in best:
            m=_best_local_match(str(video),image,float(item["time"]),duration,progress_cb=None,coarse_radius_sec=50.)
            candidates.append({"face_time":round(float(item["time"]),2),"face_hits":item["hits"],
                               "face_peak":round(item["peak"],4),"visual_time":round(float(m.get("time",0)),2),
                               "visual_score":round(float(m.get("score",0)),4)})
        report[str(ix)]={"frames":count,"clusters":len(clusters),"candidates":candidates}
        print("RG907|UNRESOLVED|"+json.dumps({"index":ix,**report[str(ix)]}),flush=True)
    return {"schema":"RG_907_3_4_RESCUE_V1","read_only":True,"xml_writes":0,"media_writes":0,
            "queue_writes":0,"auto_release":False,"results":report}
if __name__=="__main__":
    print("RG907|RESCUE_RESULT|"+json.dumps(run()),flush=True)
