#!/usr/bin/env python3
"""Read-only multi-point audio alignment diagnostic for 907; never edits files."""
from __future__ import annotations
import json,subprocess,sys
from pathlib import Path
import numpy as np
from scipy.signal import fftconvolve
VIDEO=r"\\Desktop-v7gg0en\record\907.mp4"
AUDIO=r"\\Desktop-v7gg0en\record\sound\907.mp3"
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SR=2000
POINTS=(600,4500,8500)
def ffmpeg_path():
    for p in (Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\ffmpeg\bin\ffmpeg.exe"),):
        if p.is_file():return str(p)
    import shutil
    x=shutil.which("ffmpeg")
    if x:return x
    raise RuntimeError("FFMPEG_NOT_FOUND")
def pcm(source,start,duration,ffmpeg):
    cmd=[ffmpeg,"-nostdin","-hide_banner","-loglevel","error","-ss",str(max(0,start)),"-i",source,
         "-t",str(duration),"-map","0:a:0","-vn","-ac","1","-ar",str(SR),"-f","f32le","pipe:1"]
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=150)
    if p.returncode:raise RuntimeError("FFMPEG_DECODE_FAILED: "+p.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(p.stdout,dtype="<f4").astype(np.float64)
def highpass(x):
    if len(x)<100:return x
    # First differences help remove low-frequency noise and DC offset.
    x=np.diff(x)
    return x
def match(ref,search,search_start,video_start):
    a=highpass(ref);b=highpass(search)
    if len(a)<SR*8 or len(b)<len(a)+SR*5:
        return {"status":"INSUFFICIENT_AUDIO"}
    if np.sqrt(np.mean(a*a))<1e-5 or np.sqrt(np.mean(b*b))<1e-5:
        return {"status":"SILENCE_OR_LOW_SIGNAL"}
    a=a-a.mean();b=b-b.mean()
    cc=fftconvolve(b,a[::-1],mode="valid")
    aa=np.sqrt(np.sum(a*a))
    powers=np.convolve(np.ones(1),np.ones(1)) if False else None
    # Moving energy in FFT form, avoid O(n*m).
    sq=np.pad(np.cumsum(b*b),[1,0])
    energies=np.maximum(sq[len(a):]-sq[:-len(a)],1e-16)
    scores=cc/(aa*np.sqrt(energies))
    peak_idx=int(np.argmax(scores))
    peak=float(scores[peak_idx])
    audio_time=search_start+peak_idx/SR
    return {"status":"MATCH" if peak>=.35 else "LOW_CORRELATION",
            "video_time":video_start,"audio_time":round(audio_time,3),
            "offset_audio_minus_video":round(audio_time-video_start,3),
            "normalized_correlation":round(peak,4)}
def run():
    ffmpeg=ffmpeg_path()
    rows=[]
    for v in POINTS:
        ref=pcm(VIDEO,v,12,ffmpeg)
        # Search 500 seconds both directions, clipped to valid file ranges.
        start=max(0,v-500);duration=min(11529-start,1012)
        data=pcm(AUDIO,start,duration,ffmpeg)
        row=match(ref,data,start,v);rows.append(row)
        print("RG907|AUDIO_POINT|"+json.dumps(row),flush=True)
    matches=[r for r in rows if r["status"]=="MATCH"]
    stable=(len(matches)==len(rows) and max(r["offset_audio_minus_video"] for r in matches)-
            min(r["offset_audio_minus_video"] for r in matches)<=.15)
    return {"schema":"RG907_AUDIO_ALIGNMENT_V1","read_only":True,"audio_writes":0,
            "video_writes":0,"xml_writes":0,"queue_writes":0,
            "points":rows,"stable_global_offset":stable,
            "offset_seconds":round(sum(r["offset_audio_minus_video"] for r in matches)/len(matches),3) if stable else None,
            "ready_for_montage":False}
if __name__=="__main__":
    print("RG907|AUDIO_ALIGNMENT_RESULT|"+json.dumps(run()),flush=True)
