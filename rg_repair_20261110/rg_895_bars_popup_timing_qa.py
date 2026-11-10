"""895 notification card 'БАРС' at 01:31:30, timing QA only.
Generate 15 local source frames spaced 2s from 01:31:16 through 01:31:44.
Never change source, queue, auto masks or render full stream.
"""
from pathlib import Path
import subprocess,cv2,numpy as np,json,math,hashlib
from PIL import Image,ImageDraw
ROOT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895")
OUT=ROOT/"NOTIFICATION_QA_V93"
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
def frame(t,video):
    cmd=[str(FF),"-v","error","-nostdin","-ss",str(t),"-i",str(video),
      "-frames:v","1","-f","image2pipe","-vcodec","mjpeg","pipe:1"]
    p=subprocess.run(cmd,capture_output=True,timeout=30)
    if p.returncode or not p.stdout:raise RuntimeError("FRAME_UNAVAILABLE_"+str(t))
    a=cv2.imdecode(np.frombuffer(p.stdout,np.uint8),cv2.IMREAD_COLOR)
    if a is None or a.shape[:2]!=(1080,1920):raise RuntimeError("BAD_FRAME")
    return a
def main():
    plan=json.loads((ROOT/"processing_plan.json").read_text(encoding="utf-8-sig"))
    src=plan["video"]
    times=list(range(5472,5503,2))
    w,h,cols=640,425,4
    canvas=Image.new("RGB",(w*cols,h*math.ceil(len(times)/cols)),(24,28,36))
    d=ImageDraw.Draw(canvas)
    metrics=[]
    for i,t in enumerate(times):
        a=frame(t,src)
        im=Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGR2RGB))
        # Show a context-specific outline of the bottom-right host overlay region.
        x,y,bx,bh=820,575,560,260
        ImageDraw.Draw(im).rectangle((x,y,x+bx,y+bh),outline=(255,190,50),width=5)
        px=i%cols*w;py=i//cols*h
        canvas.paste(im.resize((w,360),Image.Resampling.LANCZOS),(px,py+48))
        d.text((px+14,py+12),f"#{i:02d} | {t//3600:02d}:{t//60%60:02d}:{t%60:02d}",fill="white")
        roi=a[y:y+bh,x:x+bx]
        gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
        metrics.append({"source_second":t,"rect":[x,y,bx,bh],
           "bright_fraction":round(float((gray>175).mean()),4),
           "edge_density":round(float((cv2.Canny(gray,60,135)>0).mean()),4)})
        print("RGBARS895|FRAME|"+str(i)+"|SECOND|"+str(t),flush=True)
    output=OUT/"895_bars_notification_timing_5472_5502.jpg"
    canvas.save(output,quality=90,optimize=True)
    report={"schema":"RG895_BARS_NOTIFICATION_TIMING_QA_V1","stream":"895",
       "source_video":src,"frames":metrics,
       "suspect_overlap_spot_sample_second":5490,
       "proposed_range_requires_visual_verification":True,
       "publish_ready":False,"mask_staged":False,
       "source_and_worker_not_touched":True}
    (OUT/"895_bars_notification_timing_qa.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("RGBARS895|SHEET|"+str(output),flush=True)
    print("RGBARS895|SAFE_QA_ONLY|PASS",flush=True)
if __name__=="__main__":main()
