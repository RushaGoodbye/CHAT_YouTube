#!/usr/bin/env python3
"""Read-only pointwise A/B audio alignment. Fix 8-sec insufficient reference."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from verify_907_audio_alignment_v1 import VIDEO,AUDIO,ffmpeg_path,pcm,match
POINTS=list(range(7310,7561,15))
def main():
 ff=ffmpeg_path();rows=[]
 for t in POINTS:
  ref=pcm(VIDEO,t,12,ff)
  branches={}
  for label,shift in (("before",313.064),("after",484.24)):
   start=t+shift-12
   search=pcm(AUDIO,start,40,ff)
   r=match(ref,search,start,t)
   branches[label]={"status":r["status"],"corr":r.get("normalized_correlation"),"offset":r.get("offset_audio_minus_video")}
  good=[k for k in branches if branches[k]["status"]=="MATCH"]
  winner=max(good,key=lambda k:branches[k]["corr"]) if good else "UNRESOLVED"
  row={"video_sec":t,"winner":winner,**branches}
  rows.append(row);print("RG907|CUT_POINT_V2|"+json.dumps(row),flush=True)
 print("RG907|CUT_RESULT_V2|"+json.dumps({"read_only":True,"media_writes":0,"xml_writes":0,"rows":rows}),flush=True)
if __name__=="__main__":main()
