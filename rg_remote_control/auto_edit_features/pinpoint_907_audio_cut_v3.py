#!/usr/bin/env python3
"""Read-only narrow 907 sync split locator. Does not edit media, XML or settings."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from verify_907_audio_alignment_v1 import VIDEO,AUDIO,ffmpeg_path,pcm,match
TIMES=list(range(7300,7331,2))
def main():
 ff=ffmpeg_path();rows=[]
 for t in TIMES:
  ref=pcm(VIDEO,t,10,ff)
  states={}
  for label,shift in (("early",313.064),("late",484.197)):
   start=t+shift-7
   s=pcm(AUDIO,start,27,ff)
   r=match(ref,s,start,t)
   states[label]={"status":r["status"],"corr":r.get("normalized_correlation"),"offset":r.get("offset_audio_minus_video")}
  good=[k for k,r in states.items() if r["status"]=="MATCH"]
  winner=max(good,key=lambda k:states[k]["corr"]) if good else "UNRESOLVED"
  row={"sec":t,"winner":winner,**states};rows.append(row)
  print("RG907|SPLIT_SCAN|"+json.dumps(row),flush=True)
 before=[r["sec"] for r in rows if r["winner"]=="early"]
 after=[r["sec"] for r in rows if r["winner"]=="late"]
 result={"schema":"RG907_SPLIT_SCAN_V3","read_only":True,"media_writes":0,"xml_writes":0,
  "last_early_probe":max(before) if before else None,
  "first_late_probe":min(after) if after else None,
  "ambiguous_probe_times":[r["sec"] for r in rows if r["winner"]=="UNRESOLVED"],
  "boundary_needs_guard":True,"release_ready":False,"rows":rows}
 print("RG907|SPLIT_RESULT|"+json.dumps(result),flush=True)
if __name__=="__main__":main()
