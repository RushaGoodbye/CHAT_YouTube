#!/usr/bin/env python3
"""Read-only candidate-independent identity check for 907 screenshots 3,4,5,7,8."""
from __future__ import annotations
import json,sys
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
CANDIDATES={3:[6162.25,7166.5,8757.5],4:[8769.,7960.75,6994.],5:[7851.75,8895.5,6169.75],7:[7979.25,8769.25,7127.],8:[8715.75,7957.75,6163.75]}
def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _iter_window_ffmpeg
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    source,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not source or not Path(source).is_file():raise RuntimeError("Missing original 907")
    rows=[]
    for ix,centers in CANDIDATES.items():
        shot=cv2.imread(str(SCREEN/f"907-{ix}.jpg"))
        if shot is None:raise RuntimeError(f"Missing 907-{ix} screenshot")
        ref,_=_reference_guest_descriptor(shot)
        if ref is None:raise RuntimeError(f"Missing 907-{ix} face reference")
        options=[]
        for center in centers:
            hits=0;strong=0;peak=0.
            for t,frame in _iter_window_ffmpeg(str(source),max(0,center-15),center+15,sample_fps=.7):
                state,_,val,_,_=_frame_identity_state(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
                if state=="CURRENT":
                    hits+=1;peak=max(peak,float(val))
                    if float(val)>=.5:strong+=1
            options.append({"time":center,"face_hits":hits,"strong_hits":strong,"face_peak":round(peak,4),
                            "face_proof":hits>=2 and strong>=2 and peak>=.60})
        rows.append({"screenshot":ix,"candidates":options})
        print("RG907|GUEST_OPTION|"+json.dumps(rows[-1]),flush=True)
    return {"schema":"RG_907_REORDER_GUEST_PROOF_V1","read_only":True,
            "media_writes":0,"xml_writes":0,"queue_writes":0,"auto_release":False,
            "results":rows}
if __name__=="__main__":
    print("RG907|REORDER_GUEST_PROOF|"+json.dumps(run()),flush=True)
