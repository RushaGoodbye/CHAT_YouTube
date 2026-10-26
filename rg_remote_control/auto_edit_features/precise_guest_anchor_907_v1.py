#!/usr/bin/env python3
"""907 screenshot-precise local anchor proof, independent guest identity gate.

Uses guest-positive spans established on AlexPC #644. Reports only time/scores;
never changes production selectors, XML, media or queue.
"""
from __future__ import annotations
import json,sys
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
CASES=((1,4592.5,4550.,4620.),(2,5220.,5160.,5380.))

def validate(best,expected_start,expected_end,near_frames,identity):
    try:
        t=float(best["time"]);score=float(best["score"])
    except (KeyError,TypeError,ValueError):
        return {"verified":False,"reason":"NO_VISUAL_MATCH"}
    if not expected_start<=t<=expected_end:
        return {"verified":False,"reason":"OUTSIDE_GUEST_POSITIVE_SEGMENT",
                "time":round(t,2),"visual_score":round(score,4)}
    matches=0;peak=0.
    for sec,frame in near_frames:
        state,_,value,_,_=identity(frame)
        if state=="CURRENT":
            matches+=1
            peak=max(peak,float(value))
    ok=score>=.40 and matches>=2 and peak>=.60
    return {"verified":ok,"reason":"INDEPENDENT_VISUAL_AND_SFACE_PASS" if ok else
            "INSUFFICIENT_DOUBLE_MODAL_EVIDENCE",
            "time":round(t,2),"visual_score":round(score,4),
            "face_hits":matches,"face_peak":round(peak,4)}

def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _best_local_match,_probe_duration,_iter_window_ffmpeg
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    video,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not video or not Path(video).is_file():
        raise RuntimeError("Original video missing")
    dur=_probe_duration(video)
    rows={}
    for ix,center,low,high in CASES:
        shot=SCREEN/f"907-{ix}.jpg"
        im=cv2.imread(str(shot))
        if im is None:raise RuntimeError(f"Missing 907-{ix} source screenshot")
        ref,meta=_reference_guest_descriptor(im)
        if ref is None:raise RuntimeError(f"No guest reference for 907-{ix}")
        visual=_best_local_match(str(video),im,center,dur,progress_cb=None,
                                 coarse_radius_sec=min(110.,max(center-low,high-center)))
        try:found=float(visual.get("time",center))
        except (ValueError,TypeError):found=center
        frames=_iter_window_ffmpeg(str(video),max(low,found-17.),min(high,found+17.),
                                   sample_fps=.40)
        verdict=validate(visual,low,high,frames,
            lambda frame:_frame_identity_state(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW"))
        rows[str(ix)]=verdict
    return {"schema":"RG_907_PRECISE_GUEST_AND_VISUAL_V1",
            "read_only":True,"media_writes":0,"xml_writes":0,
            "queue_writes":0,"automatic_clock_override":False,
            "screenshots":rows,"all_verified":all(x["verified"] for x in rows.values())}

if __name__=="__main__":
    print("RG_907_PRECISE_ANCHOR|"+json.dumps(run(),ensure_ascii=False),flush=True)
