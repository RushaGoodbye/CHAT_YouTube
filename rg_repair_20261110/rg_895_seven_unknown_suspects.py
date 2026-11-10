"""RG895 selective 7 ambiguous ROI cases. Prepare one easy human QA sheet.

Unknown layout frames from independent 10-second spot audit are NOT enough
to certify source-wide notification absence. Do not add/approve masks.
"""
from pathlib import Path
from PIL import Image,ImageDraw
import subprocess,cv2,numpy as np,json,math
ROOT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895")
OUT=ROOT/"NOTIFICATION_QA_V93"
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
def get_frame(video,t):
    p=subprocess.run([str(FF),"-v","error","-nostdin","-ss",str(t),
       "-i",str(video),"-frames:v","1","-f","image2pipe","-vcodec","mjpeg","pipe:1"],
       capture_output=True,timeout=30)
    if p.returncode or not p.stdout:raise RuntimeError("FRAME_FAILED_"+str(t))
    f=cv2.imdecode(np.frombuffer(p.stdout,np.uint8),cv2.IMREAD_COLOR)
    if f is None:raise RuntimeError("CV_DECODE_FAILED")
    return Image.fromarray(cv2.cvtColor(f,cv2.COLOR_BGR2RGB))
def main():
    evidence=json.loads((OUT/"895_all64_unknown_review.json").read_text(encoding="utf-8"))
    source=json.loads((ROOT/"processing_plan.json").read_text(encoding="utf-8-sig"))["video"]
    rows=[]
    for frame in evidence["candidate_info"]:
        for layout,boxes in frame["heuristic_boxes"].items():
            for rect in boxes:
                rows.append(dict(index=len(rows),sample_index=frame["index"],
                    source_seconds=frame["source_seconds"],layout=layout,rect=rect))
    if len(rows)!=7:raise RuntimeError("SPOT_CANDIDATE_COUNT_CHANGED_"+str(len(rows)))
    cols=2;cw=960;ch=600
    canvas=Image.new("RGB",(cw*cols,ch*math.ceil(len(rows)/cols)),(20,24,30))
    draw=ImageDraw.Draw(canvas)
    for j,r in enumerate(rows):
        image=get_frame(source,r["source_seconds"])
        x,y,w,h=r["rect"]
        d=ImageDraw.Draw(image)
        d.rectangle((x,y,x+w,y+h),outline=(252,56,45),width=9)
        # Crop surrounding context but preserve full 1920x1080 view for layout
        cx=j%cols*cw;cy=j//cols*ch
        canvas.paste(image.resize((cw,540),Image.Resampling.LANCZOS),(cx,cy+57))
        t=int(r["source_seconds"])
        caption=f"#{j+1} | {t//3600:02d}:{t//60%60:02d}:{t%60:02d} | {r['layout']} | sample {r['sample_index']}"
        draw.text((cx+12,cy+12),caption,fill=(245,245,245))
        print("RG895ROI|SUSPECT|#"+str(j+1)+"|"+str(r["source_seconds"])+"|"+r["layout"]+"|"+str(r["rect"]),flush=True)
    image_path=OUT/"895_seven_suspect_rois.jpg"
    canvas.save(image_path,quality=91,optimize=True)
    report={"schema":"RG895_UNKNOWN_LAYOUT_7_ROIS_V1","stream":"895",
       "candidates":rows,"image":str(image_path),"auto_approved":False,
       "popup_coverage_verified":False,"publish_ready":False,
       "all_spot_sample_64_frames_checked":True,
       "not_exhaustive_for_unknown_layout_original_1263":True}
    (OUT/"895_seven_suspect_rois.json").write_text(
       json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("RG895ROI|SHEET|"+str(image_path),flush=True)
    print("RG895ROI|QA_BLOCK_PRESERVED|PASS",flush=True)
if __name__=="__main__":main()
