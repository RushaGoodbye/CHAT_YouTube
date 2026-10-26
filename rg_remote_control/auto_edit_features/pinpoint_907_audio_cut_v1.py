#!/usr/bin/env python3
"""Read-only fine alignment probes; uses existing audio matching code."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from verify_907_audio_alignment_v1 import VIDEO,AUDIO,ffmpeg_path,pcm,match
POINTS=list(range(7310,7551,20))
def main():
  ff=ffmpeg_path(); rows=[]
  for t in POINTS:
    reference=pcm(VIDEO,t,8,ff)
    result={}
    for label,shift in (("before",313.06),("after",484.24)):
      start=max(0,t+shift-7)
      wav=pcm(AUDIO,start,22,ff)
      found=match(reference,wav,start,t)
      result[label]={"status":found["status"],"correlation":found.get("normalized_correlation"),"offset":found.get("offset_audio_minus_video")}
    winner=max(result,key=lambda k:result[k]["correlation"] or -1)
    row={"video_sec":t,"winner":winner,"before":result["before"],"after":result["after"]}
    rows.append(row)
    print("RG907|CUT_POINT|"+json.dumps(row),flush=True)
  print("RG907|CUT_RESULT|"+json.dumps({"read_only":True,"xml_writes":0,"media_writes":0,"results":rows}),flush=True)
if __name__=="__main__":main()
