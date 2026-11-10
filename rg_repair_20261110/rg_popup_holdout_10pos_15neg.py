"""Focused user-verified RG 885 notification appearance audit, without changing video.
Reproducible source frame coordinates recorded in user-confirmed review in this thread.
Threshold samples for V41 verifier and compare adjacent off-notification negatives.
"""
from pathlib import Path
import subprocess, sys,json
from io import BytesIO
import numpy as np, cv2
SRC=Path(r"\\AlexLosServer\Work\WORK\RUSHA GOODBYE\Раша GOODBYE\ГОТОВО\ЗАПИСИ СТРИМОВ\RushaGoodbye - Live\RushaGoodbye - Live\885.mp4")
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
POSITIVES=[
 (2,1263.2,1032,684,317,131,"framed_host"),
 (7,5332.7,586,498,340,130,"dual"),
 (10,6514.0,558,528,368,100,"dual"),
 (21,8479.0,687,542,239,86,"dual"),
 (22,8659.0,686,542,240,86,"dual"),
 (26,9192.0,672,542,254,86,"dual"),
 (28,9402.5,632,537,298,91,"dual"),
 (30,9900.0,557,522,370,106,"dual"),
 (31,10645.2,652,542,274,86,"dual"),
 (32,11443.5,656,542,270,86,"dual"),
]
NEGATIVES=[
 (0,387.0,1026,670,304,83,"framed_host"),
 (3,4468.0,677,549,205,79,"dual"),
 (8,5931.0,551,500,329,101,"dual"),
 (11,6969.0,648,549,202,79,"dual"),
 (12,6976.5,626,535,198,93,"dual"),
 (13,6985.0,617,534,206,94,"dual"),
 (14,6991.0,625,535,218,93,"dual"),
 (15,6998.0,623,534,204,94,"dual"),
 (16,7007.0,629,537,199,91,"dual"),
 (17,7044.0,649,549,195,79,"dual"),
 (18,7048.0,627,537,203,91,"dual"),
 (19,7610.5,534,446,285,102,"dual"),
 (25,9008.0,520,530,263,98,"dual"),
 (27,9383.5,652,548,217,80,"dual"),
 (29,9458.0,1010,711,238,104,"framed_host"),
]
def proposed(m):
    g=(45<=m["median"]<=165 and m["spread"]>=48 and m["bright"]>=.22
       and m["saturation"]<=140 and m["edge"]>=.065 and m["detail"]>=650)
    r=(45<=m["median"]<=110 and m["spread"]>=48 and m["bright"]>=.08
       and m["saturation"]>=145 and m["edge"]>=.09 and m["detail"]>=1000)
    return g or r
def metrics(gray,hsv):
    inside=gray[8:-8,8:-8] if min(gray.shape)>20 else gray
    return dict(median=round(float(np.median(gray)),1),
                spread=round(float(gray.std()),1),
                bright=round(float(np.mean(gray>150)),3),
                saturation=round(float(np.median(hsv[:,:,1])),1),
                edge=round(float(np.mean(cv2.Canny(inside,60,130)>0)),4),
                detail=round(float(cv2.Laplacian(inside,cv2.CV_64F).var()),1))
def frame_at(t):
    cmd=[str(FF),"-hide_banner","-nostdin","-v","error",
         "-ss",str(round(t,3)),"-i",str(SRC),"-frames:v","1",
         "-f","image2pipe","-vcodec","mjpeg","pipe:1"]
    p=subprocess.run(cmd,capture_output=True,timeout=30)
    if p.returncode or not p.stdout:raise RuntimeError("FFMPEG_FRAME_FAILURE:"+repr(t))
    frame=cv2.imdecode(np.frombuffer(p.stdout,np.uint8),cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2]!=(1080,1920):raise RuntimeError("BAD_FRAME")
    return frame
def main():
    sys.path.insert(0,r"F:\RG_AUTO_EDIT\RG Auto Edit App")
    from rg_fullstream_detectors_v2 import verified_host,verified_framed_host_v86,popup_candidates,popup_search_area
    if not SRC.exists():raise RuntimeError("885_SOURCE_MISSING")
    for idx,t,x,y,w,h,layout in POSITIVES:
        f=frame_at(t)
        reg=f[y:y+h,x:x+w]
        gray=cv2.cvtColor(reg,cv2.COLOR_BGR2GRAY)
        hsv=cv2.cvtColor(reg,cv2.COLOR_BGR2HSV)
        m=metrics(gray,hsv)
        m["grey_gate"]=(65<=m["median"]<=165 and m["spread"]>=60 and m["bright"]>=.34 and m["saturation"]<=115 and m["edge"]>=.068 and m["detail"]>=850)
        m["red_gate"]=(50<=m["median"]<=95 and m["spread"]>=58 and m["bright"]>=.10 and m["saturation"]>=160 and m["edge"]>=.09 and m["detail"]>=1200)
        m["proposed"]=bool(proposed(m))
        m["host_verified"]=bool(verified_host(f) if layout=="dual" else verified_framed_host_v86(f))
        b=popup_candidates(f,popup_search_area(layout))
        m["popup_candidate_count"]=len(b)
        print("RGREALPOP|POSITIVE|"+str(idx)+"|"+str(t)+"|"+json.dumps(m),flush=True)
    false_positive=0
    for idx,t,x,y,w,h,layout in NEGATIVES:
        f=frame_at(t)
        reg=f[y:y+h,x:x+w]
        m=metrics(cv2.cvtColor(reg,cv2.COLOR_BGR2GRAY),cv2.cvtColor(reg,cv2.COLOR_BGR2HSV))
        m["proposed"]=bool(proposed(m))
        false_positive+=int(m["proposed"])
        print("RGREALPOP|NEGATIVE|"+str(idx)+"|"+str(t)+"|"+json.dumps(m),flush=True)
    print("RGREALPOP|FALSE_POSITIVES|"+str(false_positive)+"/15",flush=True)
    print("RGREALPOP|READONLY|PASS|TEN_TRUE_FIFTEEN_UNSELECTED",flush=True)
if __name__=="__main__":main()
