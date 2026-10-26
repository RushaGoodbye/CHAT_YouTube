#!/usr/bin/env python3
"""Read only: verify finished 907 reference wav against embedded MP4 audio."""
import sys,json,shutil,subprocess
from pathlib import Path
from scipy.signal import fftconvolve
import numpy as np
VIDEO=r"\\Desktop-v7gg0en\record\907.mp4"
WAV=r"F:\RG_AUTO_EDIT\RG Auto Edit Data\907_AUDIO_SYNC_RESCUE\RG_907_ALIGNED_REFERENCE_48K.wav"
POINTS=[600,4500,6737,7290,7305,7315,7319,7322,7326,7335,7609,7851,7913,7979,8715,10000,11050]
RATE=4000
def ff():
 p=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\ffmpeg\bin\ffmpeg.exe")
 return str(p) if p.is_file() else shutil.which("ffmpeg")
def pcm(f,t,d=8):
 cmd=[ff(),"-nostdin","-hide_banner","-loglevel","error","-ss",str(t),"-i",f,"-t",str(d),"-map","0:a:0","-ac","1","-ar",str(RATE),"-f","f32le","pipe:1"]
 p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
 if p.returncode:raise RuntimeError(p.stderr.decode(errors="replace")[-300:])
 return np.frombuffer(p.stdout,dtype="<f4").astype(float)
def corr(x,y):
 n=min(len(x),len(y))
 if n<RATE*6:return None
 x=np.diff(x[:n]);y=np.diff(y[:n])
 x-=x.mean();y-=y.mean()
 power=np.linalg.norm(x)*np.linalg.norm(y)
 return round(float(x.dot(y)/power),4) if power>1e-8 else None
def main():
 if not Path(WAV).is_file():raise RuntimeError("WAV_MISSING")
 rows=[]
 for t in POINTS:
  score=corr(pcm(VIDEO,t),pcm(WAV,t))
  r={"video_second":t,"waveform_correlation":score,"status":"PASS" if score is not None and score>=.3 else "REVIEW"}
  print("RG907|OUTPUT_AUDIO_QA_POINT|"+json.dumps(r),flush=True)
  rows.append(r)
 ok=all(r["status"]=="PASS" for r in rows)
 print("RG907|OUTPUT_AUDIO_QA_RESULT|"+json.dumps({"read_only":True,"source_writes":0,"xml_writes":0,"total":len(rows),"pass_count":sum(r["status"]=="PASS" for r in rows),"qa_pass":ok,"transition_needs_listening_review":True,"premiere_xml_ready":False}),flush=True)
if __name__=="__main__":main()
