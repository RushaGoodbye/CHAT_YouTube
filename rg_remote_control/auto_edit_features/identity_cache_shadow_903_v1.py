#!/usr/bin/env python3
"""Read-only 903-2 identity scan-cache evidence.

Report only aggregate classifications and timestamps; never expose embeddings,
raw image pixels, audio, video, or private source paths. No media or QA writes.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
ANCHOR=3953.5
SCAN_START=3593.5
SCAN_END=4313.5

def evidence(rows, *, anchor=ANCHOR):
    items=[(float(x["time"]),str(x.get("state") or "UNKNOWN"),float(x.get("best") or 0))
           for x in rows if isinstance(x,dict) and "time" in x]
    items.sort()
    if not items:
        return {"valid":False,"reason":"NO_ROWS"}
    first,last=items[0][0],items[-1][0]
    if abs(first-SCAN_START)>6 or abs(last-SCAN_END)>6:
        return {"valid":False,"reason":"WRONG_SCAN_WINDOW","first":round(first,1),"last":round(last,1)}
    current=[x for x in items if x[1]=="CURRENT"]
    def count(state,radius):
        return sum(1 for t,label,_ in items if label==state and abs(t-anchor)<=radius)
    nearest=min(items,key=lambda x:abs(x[0]-anchor))
    close=sorted(items,key=lambda x:abs(x[0]-anchor))[:12]
    current_near=sorted(current,key=lambda x:abs(x[0]-anchor))[:12]
    segments=[]
    for t,label,score in current:
        if not segments or t-segments[-1][-1][0]>2.6:
            segments.append([])
        segments[-1].append((t,score))
    ranked=sorted(segments,key=lambda s: min(abs(v[0]-anchor) for v in s))
    return {"valid":True,"samples":len(items),"first":round(first,2),"last":round(last,2),
        "anchor":anchor,"CURRENT_total":len(current),
        "CURRENT_45s":count("CURRENT",45),"CURRENT_180s":count("CURRENT",180),
        "OTHER_FACE_45s":count("OTHER_FACE",45),
        "PLACEHOLDER_45s":count("PLACEHOLDER",45),
        "nearest_anchor":{"time":round(nearest[0],2),"state":nearest[1],"best":round(nearest[2],3)},
        "closest_current":[{"time":round(t,2),"offset_sec":round(t-anchor,2),
                            "best":round(score,3)} for t,_,score in current_near[:5]],
        "closest_states":[{"time":round(t,2),"state":state,"best":round(score,3)} for t,state,score in close],
        "current_components":[{"start":round(s[0][0],2),"end":round(s[-1][0],2),
                              "samples":len(s),
                              "nearest_offset_sec":round(min(abs(v[0]-anchor) for v in s),2)}
                              for s in ranked[:12]]}

def run():
    if not APP.is_dir(): raise RuntimeError("Missing Studio backend")
    sys.path.insert(0,str(APP))
    from rg_guest_identity_boundary import _load_face_scan_cache
    folder=Path(os.environ.get("LOCALAPPDATA",str(Path.home()))) / "RG_AUTO_EDIT" / "face_scan_cache"
    result={"schema":"RG_903_2_IDENTITY_CACHE_SHADOW_V1","read_only":True,
            "target":"903-2","anchor":ANCHOR,"cache_dir_exists":folder.is_dir(),
            "files_considered":0,"matches":[],"media_writes":0,"xml_writes":0}
    if not folder.is_dir():
        return result
    files=sorted(folder.glob("*.pkl"),key=lambda p:p.stat().st_mtime,reverse=True)
    for f in files[:160]:
        if result["files_considered"]>=160 or len(result["matches"])>=4: break
        result["files_considered"]+=1
        try:
            if f.stat().st_size>20_000_000: continue
            rows=_load_face_scan_cache(f)
            if not rows: continue
            e=evidence(rows)
            if e.get("valid"):result["matches"].append(e)
        except Exception:
            continue
    return result

if __name__=="__main__":
    print("RG_IDENTITY_CACHE_SHADOW|"+json.dumps(run(),ensure_ascii=False),flush=True)
