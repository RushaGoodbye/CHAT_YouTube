"""Visual QA contact sheets for rejected 886 popup candidates.
Read-only video and editorial source evidence. Three sheets, labels use the
original candidate index (not sequence number).
"""
from pathlib import Path
import json,subprocess,math
from PIL import Image,ImageDraw
from io import BytesIO
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=DATA/"fullstream_v2"/"886"
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
OUT=ROOT/"HOST_POPUP_REVIEW_20261110"
def main():
    record=json.loads((ROOT/"completed_popups_v76.json").read_text(encoding="utf-8-sig"))
    candidates=record["result"]["masks"]
    rejected=json.loads((ROOT/"V41_POPUP_VISUAL_REJECTIONS.json").read_text(encoding="utf-8-sig"))
    plan=json.loads((ROOT/"processing_plan.json").read_text(encoding="utf-8-sig"))
    src=Path(plan["video"])
    if not src.is_file():raise RuntimeError("886_VIDEO_SOURCE_MISSING")
    if len(candidates)!=95 or len(rejected)!=66:raise RuntimeError("UNEXPECTED_CANDIDATE_COUNTS")
    indexes={int(r["index"]) for r in rejected}
    if len(indexes)!=66 or any(not 0<=i<95 for i in indexes):raise RuntimeError("INVALID_REJECTION_INDEX")
    OUT.mkdir(exist_ok=True)
    cellw,cellh=660,430
    cols=3;perpage=22;manifest=[]
    for page in range(math.ceil(len(rejected)/perpage)):
        items=rejected[page*perpage:(page+1)*perpage]
        rows=math.ceil(len(items)/cols)
        sheet=Image.new("RGB",(cols*cellw,rows*cellh),(23,26,33))
        painter=ImageDraw.Draw(sheet)
        for i,rejection in enumerate(items):
            index=int(rejection["index"])
            mask=candidates[index]
            a,b=map(float,mask["intervals"][0])
            sec=(a+b)/2
            cmd=[str(FF),"-hide_banner","-nostdin","-loglevel","error",
                 "-ss",str(round(sec,3)),"-i",str(src),"-frames:v","1",
                 "-f","image2pipe","-vcodec","mjpeg","pipe:1"]
            result=subprocess.run(cmd,capture_output=True,timeout=45)
            if result.returncode or not result.stdout:
                raise RuntimeError("FRAME_DECODE_FAILED:"+str(index)+":"+result.stderr.decode(errors="replace")[-300:])
            im=Image.open(BytesIO(result.stdout)).convert("RGB")
            if im.size!=(1920,1080):raise RuntimeError("BAD_IMAGE_SIZE:"+str(im.size))
            x,y,w,h=map(int,(mask[k] for k in ("x","y","width","height")))
            if not (0<=x<x+w<=1920 and 0<=y<y+h<=1080):raise RuntimeError("INVALID_BOX")
            d=ImageDraw.Draw(im)
            for inset in range(3):
                d.rectangle((x-inset,y-inset,x+w+inset,y+h+inset),outline=(255,35,35),width=3)
            thumb=im.resize((cellw,371),Image.Resampling.LANCZOS)
            left=(i%cols)*cellw;top=(i//cols)*cellh
            sheet.paste(thumb,(left,top+46))
            seconds=int(sec)
            stamp=f"{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}"
            painter.text((left+12,top+12),f"#{index:02d}    {stamp}    {mask.get('layout','unknown')}",fill="white")
            manifest.append({"candidate_index":index,"source_second":round(sec,3),
                             "source_time":stamp,"layout":mask.get("layout"),
                             "rectangle":[x,y,w,h],"intervals":mask["intervals"],
                             "rejection":rejection["reason"],"sheet":page+1})
            print("RG886SHEET|FRAME|"+str(page*perpage+i+1)+"/66|#"+str(index)+"|"+stamp,flush=True)
        filepath=OUT/f"886_rejected_notifications_part_{page+1}_of_3.jpg"
        sheet.save(filepath,quality=86,optimize=True)
        print("RG886SHEET|SHEET|"+str(filepath),flush=True)
    (OUT/"886_rejected_candidates.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    assert len(manifest)==66
    print("RG886SHEET|TOTAL|66|PAGES|3|ACCEPTED|29",flush=True)
    print("RG886SHEET|SOURCE_AND_QUEUE_UNTOUCHED|PASS",flush=True)
if __name__=="__main__":main()
