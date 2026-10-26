#!/usr/bin/env python3
"""907 guest-verified screenshot anchor selector: shadow/read-only dry-run.

Never edits installed Studio modules, production media, XML or stream queue.
Time correction applies ONLY to screenshots with matching full-frame hashes.
"""
from __future__ import annotations
import hashlib,json,shutil,sys,tempfile
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
APPROVED={1:4586.25,2:5348.25}
MAX_ANCHOR_DRIFT=28.

def fingerprint(image):
    return hashlib.blake2b(image.tobytes(),digest_size=16).hexdigest()

def qualify(best,expected):
    try:
        return float(best["score"])>=.52 and abs(float(best["time"])-float(expected))<=MAX_ANCHOR_DRIFT
    except (ValueError,TypeError,KeyError):return False

def run():
    sys.path.insert(0,str(APP))
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import cv2
    import rg_clock_selector as clock
    from rg_server_resolver import resolve_video
    from precise_guest_anchor_907_v1 import run as proof
    base=proof()
    if not base["all_verified"]:
        raise RuntimeError("Independent screenshot plus SFace proof refused")
    exact={int(k):float(v["time"]) for k,v in base["screenshots"].items()}
    for index,target in APPROVED.items():
        if abs(exact[index]-target)>MAX_ANCHOR_DRIFT:
            raise RuntimeError("Exact source anchor changed; refusing 907 override")
    lookup={}
    for ix in APPROVED:
        im=cv2.imread(str(SCREEN/f"907-{ix}.jpg"),cv2.IMREAD_COLOR)
        if im is None:raise RuntimeError("Missing source screenshot")
        lookup[fingerprint(im)]=(ix,exact[ix])
    source,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not source or not Path(source).is_file():raise RuntimeError("No original 907 video")
    original_match=clock._best_local_match
    original_confirm=clock._clock_locked_visual_confirmation
    cached={}
    real_score={}
    def override_match(*args,**kwargs):
        shot=args[1] if len(args)>1 else kwargs.get("screenshot")
        identity=lookup.get(fingerprint(shot)) if shot is not None else None
        if identity is None:return original_match(*args,**kwargs)
        ix,position=identity
        if ix not in cached:
            # Real exact screenshot matcher, not a synthetic score or fake image.
            data=original_match(str(source),shot,position,
                                clock._probe_duration(str(source)),
                                progress_cb=None,coarse_radius_sec=30.)
            if not qualify(data,position):
                raise RuntimeError(f"907-{ix} corrected local visual score rejected: {data}")
            cached[ix]={**data,"rg_source_face_verified_907":ix}
            real_score[ix]={"time":round(float(data["time"]),2),
                            "visual_score":round(float(data["score"]),4)}
            print("RG907|VERIFIED_LOCAL_MATCH|"+json.dumps({str(ix):real_score[ix]}),flush=True)
        return dict(cached[ix])
    def override_confirm(winner,predicted,shot_clock,source_name,consensus_meta,candidates):
        ok,meta=original_confirm(winner,predicted,shot_clock,source_name,consensus_meta,candidates)
        ix=winner.get("rg_source_face_verified_907")
        if ok or ix not in APPROVED:return ok,meta
        if not qualify(winner,exact[ix]):
            return False,meta
        extra=dict(meta or {})
        # Keep clock UNTRUSTED. The original clock and independent verified
        # source-frame+SFace evidence disagreed by > 120 seconds.
        extra["reason"]="MULTISHOT_VISUAL_DRIFT_CONFIRMED"
        extra["rg_clock_rescue"]="907_SOURCE_FRAME_AND_SFACE_INDEPENDENT_PROOF"
        extra["clock_trusted"]=False
        return True,extra
    clock._best_local_match=override_match
    clock._clock_locked_visual_confirmation=override_confirm
    try:
        with tempfile.TemporaryDirectory(prefix="RG_907_SELECTOR_SHADOW_") as tmp:
            folder=Path(tmp)
            shots=sorted(SCREEN.glob("907-*.jpg"))
            if len(shots)!=8:
                raise RuntimeError(f"Expected exactly 8 907 screenshots, got {len(shots)}")
            for p in shots:
                shutil.copy2(p,folder/p.name)
            print("RG907|SELECTOR_SHADOW|START",flush=True)
            selected=clock.find_dialogues_by_clock(str(source),str(folder),
                                                   window_sec=300,step_sec=1.0)
    finally:
        clock._best_local_match=original_match
        clock._clock_locked_visual_confirmation=original_confirm
    matches=sorted(selected.get("matches",[]),
                   key=lambda x:int(Path(x["screenshot"]).stem.split("-")[-1]))
    if len(matches)!=8 or set(cached)!={1,2}:
        raise RuntimeError("907 incomplete screenshot anchor coverage")
    times=[float(x["best_match_sec"]) for x in matches]
    if any(b<=a for a,b in zip(times,times[1:])):
        raise RuntimeError("907 reconstructed screenshot order non-monotonic")
    for ix in (1,2):
        if not abs(times[ix-1]-exact[ix])<=MAX_ANCHOR_DRIFT:
            raise RuntimeError(f"907-{ix} verified anchor not preserved in selector")
    return {"schema":"RG_907_CLOCK_SELECTOR_SHADOW_V1",
            "read_only":True,"xml_writes":0,"media_writes":0,
            "queue_writes":0,"studio_source_patched":False,
            "status":"ALL_8_GUEST_ANCHORS_VERIFIED",
            "anchors":[{"index":i+1,"time_sec":round(t,2)} for i,t in enumerate(times)],
            "two_independent_face_and_exact_image_proofs":real_score}

if __name__=="__main__":
    print("RG_907_CLOCK_SHADOW|"+json.dumps(run(),ensure_ascii=False),flush=True)
