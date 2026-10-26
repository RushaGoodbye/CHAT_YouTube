#!/usr/bin/env python3
"""Build a *separate* lossless aligned audio for stream 907; originals untouched.

MP3 is aligned with video via verified offsets. For unknown discontinuity
and for tail beyond MP3, the audio embedded in the MP4 is the fallback.
Outputs only to isolated target (no replacement in Studio production).
"""
from __future__ import annotations
import json,os,shutil,subprocess,sys
from pathlib import Path
VIDEO=Path(r"\\Desktop-v7gg0en\record\907.mp4")
AUDIO=Path(r"\\Desktop-v7gg0en\record\sound\907.mp3")
OUT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\907_AUDIO_SYNC_RESCUE")
DUR=11068.5
# Guarded transition deliberately exceeds the uncertain range.
CUT_A=7314.0
CUT_B=7326.0
OFFSET_A=313.064
OFFSET_B=484.197
MP3_DURATION=11529.294188
TAIL_START=11042.0 # leaves >3 seconds margin before end of MP3
def ffmpeg():
 p=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\ffmpeg\bin\ffmpeg.exe")
 if p.is_file():return str(p)
 f=shutil.which("ffmpeg")
 if f:return f
 raise RuntimeError("FFMPEG_NOT_FOUND")
def proc(cmd,timeout=30):
 p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 if p.returncode:raise RuntimeError("COMMAND_FAILED: "+p.stderr.decode(errors="replace")[-1200:])
 return p.stdout.decode(errors="replace")
def main():
 if not VIDEO.is_file() or not AUDIO.is_file():raise RuntimeError("SOURCE_MISSING")
 if not 0<CUT_A<CUT_B<TAIL_START<DUR:raise RuntimeError("INVALID_SEGMENTS")
 if TAIL_START+OFFSET_B>MP3_DURATION:raise RuntimeError("MP3_TAIL_OVERRUN")
 ff=ffmpeg();target=OUT/"RG_907_ALIGNED_REFERENCE_48K.wav"
 if target.exists():raise RuntimeError("TARGET_EXISTS_REFUSING_OVERWRITE")
 if any(OUT.glob("*.partial.wav")):raise RuntimeError("PREVIOUS_PARTIAL_NEEDS_REVIEW")
 OUT.mkdir(parents=True,exist_ok=True)
 # Raw mp3 runs except around the discontinuity. All segments are decoded
 # to consistent stereo PCM; preserve original source samples via decode only.
 pieces=[
  ("a",AUDIO,OFFSET_A,CUT_A),
  ("bridge",VIDEO,CUT_A,CUT_B-CUT_A),
  ("b",AUDIO,CUT_B+OFFSET_B,TAIL_START-CUT_B),
  ("tail",VIDEO,TAIL_START,DUR-TAIL_START)
 ]
 tmp=[]
 try:
  for label,source,start,length in pieces:
   f=OUT/(label+".partial.wav")
   cmd=[ff,"-nostdin","-hide_banner","-loglevel","error","-y","-ss",f"{start:.6f}","-i",str(source),
        "-t",f"{length:.6f}","-map","0:a:0","-vn","-ac","2","-ar","48000",
        "-c:a","pcm_s16le",str(f)]
   proc(cmd,timeout=1200)
   if not f.is_file() or f.stat().st_size<1000:raise RuntimeError("BAD_AUDIO_PIECE_"+label)
   tmp.append(f)
   print("RG907|AUDIO_PIECE|"+json.dumps({"part":label,"start":start,"length":length,"bytes":f.stat().st_size}),flush=True)
  # Concatenation via concat demuxer, no lossy recompression.
  manifest=OUT/"907_segments.partial.txt"
  manifest.write_text("".join("file '"+str(p).replace("'","'\\''")+"'\n" for p in tmp),encoding="utf-8")
  partial=OUT/"RG_907_ALIGNED_REFERENCE_48K.partial.wav"
  proc([ff,"-nostdin","-hide_banner","-loglevel","error","-y","-f","concat","-safe","0",
       "-i",str(manifest),"-c","copy",str(partial)],timeout=1200)
  if not partial.is_file() or partial.stat().st_size<1000:raise RuntimeError("BAD_OUTPUT")
  probe=shutil.which("ffprobe")
  if not probe:
   p=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\ffmpeg\bin\ffprobe.exe")
   if p.is_file():probe=str(p)
  if not probe:raise RuntimeError("FFPROBE_NOT_FOUND")
  info=json.loads(proc([probe,"-v","error","-show_entries","format=duration","-of","json",str(partial)]))
  duration=float(info["format"]["duration"])
  if abs(duration-DUR)>1.0:raise RuntimeError(f"OUTPUT_DURATION_MISMATCH {duration}")
  os.replace(partial,target)
  report={"schema":"RG907_AUDIO_RESCUE_V1","status":"GENERATED_NEEDS_LISTENING_QA",
    "stream":"907","output":str(target),"duration":duration,"originals_modified":False,
    "bridge_video_seconds":[CUT_A,CUT_B],"tail_video_seconds":[TAIL_START,DUR],
    "studio_audio_routing_unchanged":True,"premiere_xml_ready":False}
  (OUT/"RG907_AUDIO_RESCUE_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
  print("RG907|AUDIO_RESCUE_RESULT|"+json.dumps(report),flush=True)
 finally:
  for f in tmp:
   if f.is_file():f.unlink()
  m=OUT/"907_segments.partial.txt"
  if m.is_file():m.unlink()
if __name__=="__main__":main()
