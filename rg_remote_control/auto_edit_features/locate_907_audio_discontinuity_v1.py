#!/usr/bin/env python3
"""Read-only localized audio sync checks on 907, reuse tested alignment logic."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from verify_907_audio_alignment_v1 import VIDEO,AUDIO,ffmpeg_path,pcm,match
# Initial offsets +313 and +484 known; bounded windows avoid false peaks.
POINTS=[5100,6000,6800,7300,7550,7800,8000,8200,9000,9700]
def main():
  ffmpeg=ffmpeg_path();out=[]
  for v in POINTS:
    ref=pcm(VIDEO,v,12,ffmpeg)
    # Search only in the union of plausible alignment regions.
    start=v+280
    if start<0:start=0
    duration=245
    search=pcm(AUDIO,start,duration,ffmpeg)
    r=match(ref,search,start,v);out.append(r)
    print("RG907|SYNC_PROBE|"+json.dumps(r),flush=True)
  print("RG907|SYNC_MAP|"+json.dumps({"read_only":True,"video_writes":0,"audio_writes":0,"xml_writes":0,"results":out}),flush=True)
if __name__=="__main__":main()
