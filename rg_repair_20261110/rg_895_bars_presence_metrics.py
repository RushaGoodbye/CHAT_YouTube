"""Classify BARS overlay presence per timestamp from stable white alert background,
no write to production queue."""
from pathlib import Path
import subprocess,cv2,numpy as np,json,sys
ROOT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895")
OUT=ROOT/"NOTIFICATION_QA_V93"
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
def frame(src,t):
    p=subprocess.run([str(FF),"-v","error","-nostdin","-ss",str(t),"-i",str(src),
      "-frames:v","1","-f","image2pipe","-vcodec","mjpeg","pipe:1"],
      capture_output=True,timeout=30)
    if p.returncode or not p.stdout:raise RuntimeError("FFMPEG_ERROR")
    f=cv2.imdecode(np.frombuffer(p.stdout,np.uint8),cv2.IMREAD_COLOR)
    if f is None:raise RuntimeError("INVALID_FRAME")
    return f
def features(im, rect):
    x,y,w,h=rect
    f=im[y:y+h,x:x+w]
    g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)
    return {
      "bright_160":round(float((g>160).mean()),3),
      "bright_135_low_sat":round(float(((g>135)&(hsv[:,:,1]<65)).mean()),3),
      "bright_110":round(float((g>110).mean()),3),
      "median":round(float(np.median(g)),1),
      "std":round(float(np.std(g)),1)}
def main():
    job=json.loads((ROOT/"processing_plan.json").read_text(encoding="utf-8-sig"))
    src=job["video"]
    # BARS overlay is visibly near video ROI x850..1344 y~710..806.
    # Also compare a stable adjacent region as false-positive control.
    rects={"alert_upper":[850,610,500,68],"alert_lower":[850,715,500,93],
           "control":[850,805,500,85]}
    for t in range(5470,5505,2):
        im=frame(src,t)
        row={k:features(im,v) for k,v in rects.items()}
        print("RG895BARSSTATS|"+str(t)+"|"+json.dumps(row),flush=True)
    print("RG895BARSSTATS|READ_ONLY|PASS",flush=True)
if __name__=="__main__":main()
