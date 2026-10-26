#!/usr/bin/env python3
"""Read-only aligned WAV QA with lag tolerance 100ms. Never alters assets."""
import json,subprocess,shutil
from pathlib import Path
import numpy as np
from scipy.signal import fftconvolve
VIDEO=r"\\Desktop-v7gg0en\record\907.mp4"
WAV=r"F:\RG_AUTO_EDIT\RG Auto Edit Data\907_AUDIO_SYNC_RESCUE\RG_907_ALIGNED_REFERENCE_48K.wav"
P=[600,4500,6737,7290,7305,7315,7319,7322,7326,7335,7609,7851,7913,7979,8715,10000,11050]
SR=4000
def pcm(src,t,span):
 p=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\ffmpeg\bin\ffmpeg.exe")
 ff=str(p) if p.is_file() else shutil.which("ffmpeg")
 r=subprocess.run([ff,"-nostdin","-hide_banner","-loglevel","error","-ss",str(t),"-i",src,"-t",str(span),"-map","0:a:0","-ac","1","-ar",str(SR),"-f","f32le","pipe:1"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
 if r.returncode:raise RuntimeError(r.stderr.decode(errors="replace")[-200:])
 return np.frombuffer(r.stdout,dtype="<f4").astype(np.float64)
def compare(t):
 # Video sample is 8s; WAV is 8.4s with +/-0.2 s margin
 a=pcm(VIDEO,t,8.0)
 b=pcm(WAV,max(0,t-.2),8.4)
 if len(a)<SR*7 or len(b)<len(a)+SR//5:return {"status":"SHORT"}
 a=np.diff(a);b=np.diff(b);a-=a.mean();b-=b.mean()
 cross=fftconvolve(b,a[::-1],mode="valid")
 c=np.pad(np.cumsum(b*b),[1,0])
 en=np.maximum(c[len(a):]-c[:-len(a)],1.e-20)
 scores=cross/(np.linalg.norm(a)*np.sqrt(en)+1.e-20)
 idx=int(np.argmax(scores))
 lag=round(max(0,t-.2)+idx/SR-t,4)
 score=round(float(scores[idx]),4)
 ok=(score>=.35 and abs(lag)<=.10)
 return {"status":"PASS" if ok else "REVIEW","correlation":score,"lag_seconds":lag}
def main():
 rows=[]
 for t in P:
  r={"video_second":t,**compare(t)};rows.append(r)
  print("RG907|WAV_LAG_POINT|"+json.dumps(r),flush=True)
 print("RG907|WAV_LAG_RESULT|"+json.dumps({"read_only":True,"points":len(rows),"passes":sum(r["status"]=="PASS" for r in rows),"review":[r for r in rows if r["status"]!="PASS"],"needs_listening_review":True,"release_ready":False}),flush=True)
if __name__=="__main__":main()
