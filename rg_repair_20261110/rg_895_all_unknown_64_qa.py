"""RG895 prioritized unknown-layout notification screen audit.
Use the already saved 10s spot-sample manifest and source video to produce
full contact sheets for ALL 64 classified unknown times, plus ROI heuristic
scores, without changing existing masks, statuses, ASR or Studio.
"""
from pathlib import Path
import json,hashlib,os,sys,math,subprocess
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
ROOT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895")
OUT=ROOT/"NOTIFICATION_QA_V93"
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
sys.path.insert(0,str(APP))
from rg_fullstream_detectors_v2 import (popup_candidates,popup_search_area,
    verified_host,verified_single_host,verified_framed_host_v86)
def get_frame(src,t):
    args=[str(FF),"-hide_banner","-nostdin","-loglevel","error",
      "-ss",str(round(t,3)),"-i",str(src),"-frames:v","1","-vcodec","mjpeg",
      "-f","image2pipe","pipe:1"]
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    if p.returncode or not p.stdout:raise RuntimeError("FRAME_UNAVAILABLE_"+str(t))
    result=cv2.imdecode(np.frombuffer(p.stdout,np.uint8),cv2.IMREAD_COLOR)
    if result is None or result.shape[:2]!=(1080,1920):raise RuntimeError("INVALID_FRAME_"+str(t))
    return result
def checks(frame):
    # These are exploratory, not render approval. Handle unknown layouts
    # by testing both host ROIs without relying on host verification.
    result={}
    for layout in ("dual","framed_host"):
        roi=popup_search_area(layout)
        candidates=popup_candidates(frame,roi)
        result[layout]=[list(map(int,b)) for b in candidates]
    return result
def sheet(rows,path):
    cw,ch,thumbh=640,408,360
    cols=3
    count=len(rows);height=math.ceil(count/cols)*ch
    canvas=Image.new("RGB",(cw*cols,height),"#11151b")
    draw=ImageDraw.Draw(canvas)
    for ix,r in enumerate(rows):
        x=(ix%cols)*cw;y=(ix//cols)*ch
        image=Image.fromarray(cv2.cvtColor(r["frame"],cv2.COLOR_BGR2RGB))
        border=ImageDraw.Draw(image)
        for rect in r["heuristic_boxes"]["dual"]:
            bx,by,bw,bh=rect;border.rectangle((bx,by,bx+bw,by+bh),outline=(255,55,48),width=7)
        for rect in r["heuristic_boxes"]["framed_host"]:
            bx,by,bw,bh=rect;border.rectangle((bx,by,bx+bw,by+bh),outline=(247,194,55),width=6)
        canvas.paste(image.resize((cw,thumbh),Image.Resampling.LANCZOS),(x,y+47))
        t=r["source_seconds"]
        label=f"#{r['index']:02d} {int(t)//3600:02d}:{(int(t)//60)%60:02d}:{int(t)%60:02d} D:{len(r['heuristic_boxes']['dual'])} F:{len(r['heuristic_boxes']['framed_host'])}"
        draw.text((x+12,y+13),label,fill=(246,246,251))
    canvas.save(path,quality=91,optimize=True)
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    current=json.loads((ROOT/"status.json").read_text(encoding="utf-8-sig"))
    manifest=json.loads((OUT/"895_review_manifest.json").read_text(encoding="utf-8-sig"))
    if current.get("state")!="PAUSED_EDITORIAL_QA":raise RuntimeError("895_NOT_PAUSED")
    if manifest["layout_counts_10s_spot_check"]["unknown"]!=64:raise RuntimeError("UNKNOWN_SAMPLE_SET_CHANGED")
    src=Path(manifest["source_video"])
    times=sorted(set(map(float,manifest["unclassified_sample_times"])))
    if len(times)!=64:raise RuntimeError("UNKNOWN_TIMECODE_COUNT_CHANGED")
    rows=[]
    for idx,t in enumerate(times):
        frame=get_frame(src,t)
        hypothesis=checks(frame)
        rows.append({"index":idx,"source_seconds":t,"frame":frame,"heuristic_boxes":hypothesis})
        if (idx+1)%12==0:print("RG895UNCLASS|FRAMES|"+str(idx+1)+"/64",flush=True)
    pages=[]
    for idx in range(0,len(rows),12):
        outfile=OUT/f"895_unknown_all64_part_{idx//12+1:02d}.jpg"
        sheet(rows[idx:idx+12],outfile)
        pages.append(str(outfile))
    result={"schema":"RG895_UNCLASSIFIED_ALL_64_SAMPLE_AUDIT_V1","stream":"895",
        "input_spot_scan_unknown_count":64,
        "sample_stride_seconds":10,
        "reviewed_in_earlier_sheet":18,
        "all_spot_sample_times":times,
        "candidate_info":[{"index":r["index"],"source_seconds":r["source_seconds"],
              "heuristic_boxes":r["heuristic_boxes"]} for r in rows],
        "contact_sheets":pages,
        "candidate_counts":{"dual":sum(len(r["heuristic_boxes"]["dual"]) for r in rows),
              "framed_host":sum(len(r["heuristic_boxes"]["framed_host"]) for r in rows)},
        "red_box_means_heuristic_dual_candidate":True,
        "yellow_box_means_heuristic_framed_candidate":True,
        "does_not_certify_total_source_notification_coverage":True,
        "popup_coverage_verified":False,
        "publish_ready":False}
    path=OUT/"895_all64_unknown_review.json"
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    if json.loads((ROOT/"status.json").read_text(encoding="utf-8-sig"))!=current:
        raise RuntimeError("STATUS_CHANGED_DURING_READ_ONLY_QA")
    print("RG895UNCLASS|TOTAL|64|SHEETS|"+str(len(pages)),flush=True)
    print("RG895UNCLASS|DUAL_ROI_CANDIDATES|"+str(result["candidate_counts"]["dual"]),flush=True)
    print("RG895UNCLASS|FRAMED_ROI_CANDIDATES|"+str(result["candidate_counts"]["framed_host"]),flush=True)
    print("RG895UNCLASS|REPORT|"+str(path),flush=True)
    print("RG895UNCLASS|NO_RENDER_NO_ASR_NO_PLAN_EDITS|PASS",flush=True)
if __name__=="__main__":main()
