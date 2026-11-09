"""RG V4: no-face screenshot visual + wall-clock evidence gate.

A screenshot of a card, object or empty guest region may be a genuine time
reference. It does NOT establish a guest identity. This gate checks a distinct
scene match between two independently verified neighbour anchors; weak or
repeated UI matching fails closed. No montage, file mutation or network.
"""
from __future__ import annotations

VERSION="RG_SCENE_TIME_NO_FACE_V4"

def eligible_preflight(info, screenshot):
    """Keep a no-face shot only for an attempted independent time/scene check."""
    from pathlib import Path
    if str((info or {}).get("reason"))!="NO_GUEST_IN_RIGHT_WINDOW":
        return False
    p=Path(screenshot)
    if not p.is_file() or p.stat().st_size<1024:
        return False
    import cv2
    import numpy as np
    from rg_clock_selector import read_clock_from_screenshot
    im=cv2.imread(str(p),cv2.IMREAD_COLOR)
    if im is None or min(im.shape[:2])<200:
        return False
    right=im[:,im.shape[1]//2:]
    if float(np.std(right))<15.0:
        return False
    try:
        stamp=read_clock_from_screenshot(p)
    except (OSError,RuntimeError,ValueError):
        return False
    return bool(stamp and stamp.get("seconds_of_day") is not None)

def prove_scene(video_path, records, index, original, video_duration, previous_confirmed):
    """Return strong independent evidence or raise without changing the anchor."""
    if len(records)<2:
        raise RuntimeError("SCENE_TIME_NEIGHBORS_UNAVAILABLE")
    rec=records[index]
    curclock=(rec.get("clock") or {}).get("seconds_of_day")
    if curclock is None:
        raise RuntimeError("SCENE_TIME_SCREENSHOT_CLOCK_UNREADABLE")
    prev=records[index-1] if index>0 else None
    nxt=records[index+1] if index+1<len(records) else None
    if not (prev or nxt):
        raise RuntimeError("SCENE_TIME_NEIGHBOR_REQUIRED")
    if previous_confirmed is not None and original<=float(previous_confirmed)+2.0:
        raise RuntimeError("SCENE_TIME_ORDER_VIOLATION")
    if nxt and original>=float(nxt["winner"]["time"])-2.0:
        raise RuntimeError("SCENE_TIME_NEXT_ANCHOR_CONFLICT")
    if not 0.<original<float(video_duration):
        raise RuntimeError("SCENE_TIME_OUT_OF_VIDEO")
    comparisons=[]
    for neighbor in (prev,nxt):
        if neighbor is None:
            continue
        nt=float(neighbor["winner"]["time"])
        nc=(neighbor.get("clock") or {}).get("seconds_of_day")
        if nc is None:
            raise RuntimeError("SCENE_TIME_NEIGHBOR_CLOCK_UNREADABLE")
        visual_gap=original-nt
        clock_gap=((float(curclock)-float(nc)+43200.)%86400.)-43200.
        if abs(visual_gap-clock_gap)>180.0:
            raise RuntimeError("SCENE_TIME_CLOCK_NEIGHBOR_DISAGREEMENT")
        comparisons.append((nt,visual_gap,clock_gap))
    if len(comparisons)<1:
        raise RuntimeError("SCENE_TIME_INSUFFICIENT_NEIGHBORS")
    from rg_clock_selector import _best_local_match
    shot=rec["shot"]
    # Independent video decode, not cached fingerprint winner.
    local=_best_local_match(video_path,shot,original,video_duration,
                            progress_cb=None,coarse_radius_sec=12.)
    score=float(local.get("score") or 0.0)
    local_time=float(local.get("time") or -1.0)
    if score<0.60 or abs(local_time-original)>18.0:
        raise RuntimeError(f"SCENE_TIME_LOCAL_VISUAL_NOT_VERIFIED score={score:.3f}")
    controls=[]
    for nt,_,_ in comparisons:
        # A repeated static interface/card will match at both other dialogues.
        # Check the same screenshot at those independent, known video moments.
        control=_best_local_match(video_path,shot,nt,video_duration,
                                   progress_cb=None,coarse_radius_sec=12.)
        controls.append(float(control.get("score") or 0.0))
    contrast=score-max(controls)
    if contrast<0.05:
        raise RuntimeError(f"SCENE_TIME_NOT_DISTINCT_FROM_NEIGHBORS score={score:.3f}, control={max(controls):.3f}")
    return {
        "accepted":True,"policy":VERSION,"reason":"NO_FACE_TIME_SCENE_VERIFIED",
        "frame_time_sec":round(original,3),"independent_match_time_sec":round(local_time,3),
        "scene_score":round(score,5),"neighbor_control_scores":[round(x,5) for x in controls],
        "contrast":round(contrast,5),
        "clock_gap_error_sec":[round(abs(a-b),3) for _,a,b in comparisons],
        "face_identity_proven":False,
        "boundary_verification_still_required":True,
    }
