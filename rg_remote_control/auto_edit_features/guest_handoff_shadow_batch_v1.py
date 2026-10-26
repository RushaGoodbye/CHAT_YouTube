#!/usr/bin/env python3
"""RG Auto Edit: 901/905 face-and-audio handoff evidence, shadow only.

Uses installed OpenCV SFace, FFmpeg and optional local Silero VAD; no model
downloads, no exports, no edits, no embedding/image/audio content in logs.
Deliberately never approves an automatic trim or changes QA status.
"""
from __future__ import annotations
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
CASES=(
    ("901",4,5,366773,371616,15.0),
    ("901",5,6,372083,375966,15.0),
    ("905",1,2,167719,167920,1.4),
)
FPS=30.0

def local_media_path(url: str):
    if not url or "\0" in url:
        return None
    if re.match(r"^[A-Za-z]:[\\/]",url):
        return Path(url)
    split=urllib.parse.urlsplit(url)
    if split.scheme != "file":
        return None
    value=urllib.parse.unquote(split.path)
    if split.netloc:
        return Path("\\\\" + split.netloc + value.replace("/","\\"))
    if re.match(r"^/[A-Za-z]:/",value):
        value=value[1:]
    return Path(value.replace("/","\\"))

def xml_sources(path: Path, kind: str):
    if not path.is_file() or path.stat().st_size > 50000000:
        raise RuntimeError("Missing/big XML")
    root=ET.parse(path).getroot()
    urls=[(x.text or "") for x in root.findall(f".//sequence/media/{kind}//pathurl")]
    found=[]
    for url in urls:
        p=local_media_path(url)
        if p and p.is_file() and p not in found:
            found.append(p)
    return found

def intervals_from_xml(path: Path, kind: str):
    root=ET.parse(path).getroot()
    vals=[]
    for clip in root.findall(f".//sequence/media/{kind}/track/clipitem"):
        # Prefer actual original-source clip ranges; exclude title and overlay
        if kind=="video":
            name=clip.findtext("name") or ""
            master=clip.findtext("masterclipid") or ""
            if not re.search(r"\.(mp4|mkv|mov|avi)$",name,re.I): continue
            if master and master!="masterclip-video": continue
        try:
            a,b=int(clip.findtext("in")),int(clip.findtext("out"))
            if b>a: vals.append((a,b))
        except (TypeError,ValueError):
            pass
    return (min((a for a,b in vals),default=None),
            max((b for a,b in vals),default=None))

def case_inputs(app,case):
    stream,left,right,first,last,step=case
    base=app/stream
    xml_left=base/f"RG_EDITED_{stream}_{left}.xml"
    xml_right=base/f"RG_EDITED_{stream}_{right}.xml"
    for p in (xml_left,xml_right):
        if not p.is_file(): raise RuntimeError("Missing primary XML")
    spans=(intervals_from_xml(xml_left,"video"), intervals_from_xml(xml_right,"video"))
    actual=max(0,min(spans[0][1],spans[1][1])-max(spans[0][0],spans[1][0]))
    if actual!=last-first or max(spans[0][0],spans[1][0])!=first:
        raise RuntimeError("Boundary interval changed from separately verified QA")
    media=[xml_sources(p,"video") for p in (xml_left,xml_right)]
    shared=[x for x in media[0] if x in media[1]]
    if len(shared)!=1:
        raise RuntimeError("No unique shared video source in adjacent XML")
    return xml_left,xml_right,shared[0]

def sample_times(start,end,step):
    if end<=start or step<=0:raise RuntimeError("invalid bounds")
    count=min(24,max(3,int(math.ceil((end-start)/step))+1))
    return [round(start+i*(end-start)/(count-1),3) for i in range(count)]

def classify_frame(frame, left_ref,right_ref):
    from rg_guest_identity_boundary import _frame_identity_state
    label,sims,best,nfaces,_embedding=_frame_identity_state(
        frame,{"GUEST_LEFT":left_ref,"GUEST_RIGHT":right_ref},
        layout_mode="RIGHT_WINDOW",floor=.42,hard_floor=.48)
    return {"state":label,"score":round(float(best),4),"guest_faces":int(nfaces),
            "comparison_gap":round(abs(float(sims.get("0:GUEST_LEFT",0))-
                                        float(sims.get("0:GUEST_RIGHT",0))),4)
                if sims else 0}

def visual_probe(video,refs,first,last,step):
    import cv2
    from rg_clock_selector import _iter_window_ffmpeg
    from rg_guest_identity_boundary import _reference_guest_descriptor
    shotrefs=[]
    for file in refs:
        data=cv2.imread(str(file))
        desc,meta=_reference_guest_descriptor(data)
        if desc is None:
            return {"state":"REFERENCE_UNAVAILABLE","reasons":[x.get("reason") for x in (meta,)]}
        shotrefs.append(desc)
    stamps=sample_times(first/FPS,last/FPS,step)
    output=[]
    # Read only one decoder window, not one multi-hour random seek per frame.
    rate=1.0/max(.2,float((stamps[-1]-stamps[0])/max(1,len(stamps)-1)))
    iterator=_iter_window_ffmpeg(str(video),float(stamps[0]),float(stamps[-1])+.6,
                                 sample_fps=rate)
    for t,frame in iterator:
        t=float(t)
        if t < float(stamps[0])-.7 or t > float(stamps[-1])+1:continue
        result=classify_frame(frame,*shotrefs)
        result["source_sec"]=round(t,2)
        output.append(result)
        if len(output)>=27:break
    counts={label:sum(x["state"]==label for x in output)
            for label in ("GUEST_LEFT","GUEST_RIGHT","OTHER_FACE","PLACEHOLDER","UNKNOWN")}
    return {"state":"EVIDENCE_ONLY","reference_faces_available":True,"samples":output,
            "counts":counts,"sampled":len(output),
            "guest_handoff_approved":False}

def pcm_from_source(audio:Path, t0:float, dur:float):
    import numpy as np
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None, "FFMPEG_MISSING"
    if dur<.1 or dur>18:return None,"BAD_AUDIO_WINDOW"
    cmd=[str(ffmpeg),"-nostdin","-hide_banner","-loglevel","error",
         "-ss",f"{t0:.3f}","-i",str(audio),"-t",f"{dur:.3f}",
         "-vn","-ac","1","-ar","16000","-f","f32le","pipe:1"]
    try:
        p=subprocess.run(cmd,capture_output=True,timeout=40,
                         creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if p.returncode or not p.stdout:return None,"FFMPEG_AUDIO_DECODE_FAILED"
        return np.frombuffer(p.stdout,dtype="<f4").copy(),None
    except (subprocess.TimeoutExpired,OSError):
        return None,"FFMPEG_AUDIO_TIMEOUT"

def audio_probe(left_xml,right_xml,start,end):
    from pathlib import Path
    import numpy as np
    audio=[xml_sources(p,"audio") for p in (left_xml,right_xml)]
    shared=[p for p in audio[0] if p in audio[1]]
    if len(shared)!=1:
        return {"status":"AUDIO_PATH_NOT_SHARED","vad_pass":False}
    ai=intervals_from_xml(left_xml,"audio")
    vi=intervals_from_xml(left_xml,"video")
    aj=intervals_from_xml(right_xml,"audio")
    vj=intervals_from_xml(right_xml,"video")
    if None in (ai+vi+aj+vj):
        return {"status":"NO_SOURCE_AUDIO_OFFSETS","vad_pass":False}
    offsets=(ai[0]-vi[0],aj[0]-vj[0])
    if abs(offsets[0]-offsets[1])>2:
        return {"status":"AUDIO_OFFSET_CONFLICT","offsets_frames":offsets,"vad_pass":False}
    audio_start=(start+offsets[0])/FPS
    audio_end=(end+offsets[0])/FPS
    pad=2.0
    sample,error=pcm_from_source(shared[0],max(0.,audio_start-pad),audio_end-audio_start+2*pad)
    if error:return {"status":error,"vad_pass":False}
    if len(sample)<1600:return {"status":"AUDIO_TOO_SHORT","vad_pass":False}
    frame=1600
    rms=[float(np.sqrt(np.mean(x*x))) for x in
         (sample[k:k+frame] for k in range(0,len(sample)-frame+1,frame))]
    n_above=sum(float(v)>10**(-35/20) for v in rms)
    out={"status":"AUDIO_LEVEL_MEASURED","offset_consistent":True,
         "active_rms_windows_above_minus35db":n_above,
         "total_100ms_windows":len(rms),"peak_rms_db":round(20*math.log10(max(rms)+1e-9),2),
         "vad_pass":False}
    # Silero output only as timing evidence: silence != permission to trim video.
    try:
        from silero_vad import load_silero_vad, get_speech_timestamps
        import torch
        torch.set_num_threads(2)
        model=load_silero_vad()
        stamps=get_speech_timestamps(torch.from_numpy(sample),model,sampling_rate=16000,
                                     return_seconds=True)
        out["vad_spans_seconds"]=[[round(float(s["start"]),2),round(float(s["end"]),2)]
                                  for s in stamps[:60]]
        out["speech_overlap_span_count"]=sum(
            float(s["end"])>pad and float(s["start"])<((end-start)/FPS+pad)
            for s in stamps)
        out["status"]="VAD_EVIDENCE_ONLY"
    except Exception as exc:
        out["vad_reason"]=type(exc).__name__
    return out

def run(app=APP,shots=SCREEN):
    sys.path.insert(0,str(app))
    out={"schema":"RG_GUEST_HANDOFF_SHADOW_BATCH_V1","read_only":True,
         "media_writes":0,"xml_writes":0,"qa_writes":0,
         "auto_trim":False,"results":[]}
    for case in CASES:
        stream,left,right,first,last,step=case
        report={"stream":stream,"pair":[left,right],"overlap_frames":last-first,
                "overlap_seconds":round((last-first)/FPS,2)}
        try:
            lx,rx,video=case_inputs(app,case)
            refs=(shots/f"{stream}-{left}.jpg",shots/f"{stream}-{right}.jpg")
            report["visual"]=visual_probe(video,refs,first,last,step)
            report["audio"]=audio_probe(lx,rx,first,last)
        except Exception as exc:
            report["failure"]=type(exc).__name__
            report["reason"]=str(exc)[:160]
        out["results"].append(report)
    return out

if __name__=="__main__":
    print("RG_GUEST_HANDOFF_SHADOW|" + json.dumps(run(),ensure_ascii=False),flush=True)
