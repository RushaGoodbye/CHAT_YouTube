"""885 visual review sheet: 25 rejected popup candidates, non-destructive.
Decode source timestamp into temporary JPEG previews, annotate source-time and rejected index.
No original MP4, rendered video, cache or queue changes; no app changes.
"""
from pathlib import Path
import json,subprocess,sys,math,time
from PIL import Image,ImageDraw,ImageFont
from io import BytesIO
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=DATA/"fullstream_v2"/"885"
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
OUT=ROOT/"HOST_POPUP_REVIEW_20261110"
def main():
    manifest=json.loads((ROOT/"completed_popups_v76.json").read_text(encoding="utf-8-sig"))
    masks=manifest["result"]["masks"]
    rejected=json.loads((ROOT/"V41_POPUP_VISUAL_REJECTIONS.json").read_text(encoding="utf-8-sig"))
    plan=json.loads((ROOT/"processing_plan.json").read_text(encoding="utf-8-sig"))
    source=Path(plan["video"])
    if not source.is_file():raise RuntimeError("VIDEO_SOURCE_UNAVAILABLE")
    if len(rejected)!=25 or len(masks)!=33:raise RuntimeError("CANDIDATE_COUNTS_CHANGED")
    OUT.mkdir(exist_ok=True)
    width,height=560,370
    cols=4
    rows=math.ceil(len(rejected)/cols)
    sheet=Image.new("RGB",(width*cols,height*rows),(25,28,35))
    draw=ImageDraw.Draw(sheet)
    enriched=[]
    for i,item in enumerate(rejected):
        idx=int(item["index"]);mask=masks[idx]
        begin,end=map(float,mask["intervals"][0])
        t=(begin+end)*.5
        cmd=[str(FF),"-hide_banner","-nostdin","-loglevel","error",
             "-ss",str(round(t,3)),"-i",str(source),"-frames:v","1",
             "-f","image2pipe","-vcodec","mjpeg","pipe:1"]
        result=subprocess.run(cmd,capture_output=True,timeout=50)
        if result.returncode or not result.stdout:
            raise RuntimeError("FRAME_DECODE_FAILED_"+str(idx)+":"+result.stderr[-200:].decode(errors="replace"))
        im=Image.open(BytesIO(result.stdout)).convert("RGB")
        if im.size!=(1920,1080):raise RuntimeError("INVALID_SOURCE_FRAME")
        x,y,w,h=(int(mask[k]) for k in ("x","y","width","height"))
        painter=ImageDraw.Draw(im)
        for off in range(3):painter.rectangle((x-off,y-off,x+w+off,y+h+off),outline="#ff3232",width=2)
        thumb=im.resize((width,315),Image.Resampling.LANCZOS)
        left=(i%cols)*width;top=(i//cols)*height
        sheet.paste(thumb,(left,top+40))
        sec=int(t)
        stamp=f"{sec//3600:02}:{(sec//60)%60:02}:{sec%60:02}"
        draw.text((left+8,top+10),f"#{idx:02d}  {stamp}  {mask['layout']}",fill="white")
        enriched.append({"index":idx,"time_seconds":round(t,3),
                         "time_hms":stamp,"layout":mask["layout"],
                         "rectangle":[x,y,w,h],"rejection":item["reason"]})
        print("RGHOSTSHEET|FRAME|"+str(i+1)+"/25|"+str(idx)+"|"+stamp,flush=True)
    path=OUT/"885_rejected_notifications_contact_sheet.jpg"
    sheet.save(path,quality=85,optimize=True)
    (OUT/"885_rejected_candidates.json").write_text(json.dumps(enriched,ensure_ascii=False,indent=2),encoding="utf-8")
    print("RGHOSTSHEET|SHEET|"+str(path),flush=True)
    print("RGHOSTSHEET|REJECTED|25|CANDIDATES|33|APPROVED|8",flush=True)
    print("RGHOSTSHEET|NO_RENDER_OR_QA_CHANGED|PASS",flush=True)
if __name__=="__main__":main()
