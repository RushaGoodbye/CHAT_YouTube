"""RG895 non-destructive notification editorial evidence.
Build contact sheets for the 3 detector rejected candidates and
sampled unclassified scene frames. Does NOT certify source-wide coverage.
No production video rendering or queue changes.
"""
from pathlib import Path
import json,subprocess,math,sys,hashlib
from io import BytesIO
import numpy as np,cv2
from PIL import Image,ImageDraw
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
ROOT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895")
OUT=ROOT/"NOTIFICATION_QA_V93"
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
def frame_at(video,t):
    cmd=[str(FF),"-hide_banner","-nostdin","-loglevel","error","-ss",str(round(t,3)),
         "-i",str(video),"-frames:v","1","-f","image2pipe","-vcodec","mjpeg","pipe:1"]
    p=subprocess.run(cmd,capture_output=True,timeout=55)
    if p.returncode or not p.stdout:raise RuntimeError("FFMPEG_FRAME_FAILED:"+str(t))
    bgr=cv2.imdecode(np.frombuffer(p.stdout,np.uint8),cv2.IMREAD_COLOR)
    if bgr is None or bgr.shape[:2]!=(1080,1920):raise RuntimeError("BAD_FRAME")
    return bgr
def classify(frame,functions):
    host,solo,framed=functions
    if host(frame):return "dual"
    if solo(frame):return "solo"
    if framed(frame):return "framed_host"
    return "unknown"
def make_sheet(cards,path,columns=3):
    cw,ch=650,415
    rows=math.ceil(len(cards)/columns)
    dst=Image.new("RGB",(cw*columns,ch*rows),(21,25,31))
    draw=ImageDraw.Draw(dst)
    for i,card in enumerate(cards):
        x=(i%columns)*cw;y=(i//columns)*ch
        img=Image.fromarray(cv2.cvtColor(card["frame"],cv2.COLOR_BGR2RGB))
        if card.get("rect"):
            p=ImageDraw.Draw(img)
            bx,by,bw,bh=card["rect"]
            p.rectangle((bx,by,bx+bw,by+bh),outline=(255,40,40),width=8)
        img=img.resize((cw,366),Image.Resampling.LANCZOS)
        dst.paste(img,(x,y+45))
        draw.text((x+12,y+12),card["caption"],fill=(246,248,251))
    dst.save(path,quality=88,optimize=True)
def main():
    import sys
    sys.path.insert(0,str(APP))
    from rg_fullstream_detectors_v2 import verified_host,verified_single_host,verified_framed_host_v86
    functions=(verified_host,verified_single_host,verified_framed_host_v86)
    plan=json.loads((ROOT/"processing_plan.json").read_text(encoding="utf-8-sig"))
    src=Path(plan["video"]);duration=float(plan["duration_seconds"])
    if not src.is_file():raise RuntimeError("SOURCE_VIDEO_NOT_FOUND")
    result=json.loads((ROOT/"completed_popups_v76.json").read_text(encoding="utf-8-sig"))["result"]
    rejects=json.loads((ROOT/"V41_POPUP_VISUAL_REJECTIONS.json").read_text(encoding="utf-8-sig"))
    if len(rejects)!=3 or len(result["masks"])!=23 or len(plan["popup_masks"])!=20:
        raise RuntimeError("QA_STATE_CHANGED_STOP")
    OUT.mkdir(parents=True,exist_ok=True)
    cards=[];notes=[]
    for item in rejects:
        idx=int(item["index"]);m=result["masks"][idx];start,end=m["intervals"][0]
        t=(float(start)+float(end))/2
        frame=frame_at(src,t)
        label=classify(frame,functions)
        cards.append(dict(frame=frame,rect=[m[k] for k in ("x","y","width","height")],
                          caption=f"REJECT #{idx:02d} | {int(t)//3600:02d}:{int(t)//60%60:02d}:{int(t)%60:02d} | {label}"))
        notes.append(dict(kind="REJECTED_POPUP",candidate_index=idx,source_seconds=round(t,3),layout=label,
                          box=[m[k] for k in ("x","y","width","height")],reason=item["reason"]))
    make_sheet(cards,OUT/"895_three_rejected_candidates.jpg")
    print("RG895QA|REJECTIONS|3|SHEET|"+str(OUT/"895_three_rejected_candidates.jpg"),flush=True)
    # 10-second independent source-timeline spot audit, no reprocessing source ASR.
    # This is a sampling guide, NOT a proof that all unknown source frames were inspected.
    targets=[float(t) for t in range(0,int(duration),10)]
    totals={"dual":0,"solo":0,"framed_host":0,"unknown":0}
    unknown=[]
    # One sequential FFmpeg decode, not 1148 expensive NAS seeks.
    cmd=[str(FF),"-hide_banner","-nostdin","-loglevel","error","-i",str(src),
         "-vf","fps=1/10:start_time=0","-an","-sn","-pix_fmt","bgr24",
         "-f","rawvideo","pipe:1"]
    import tempfile
    with tempfile.TemporaryFile(mode="w+b") as err:
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=err,stdin=subprocess.DEVNULL)
        try:
            size=1920*1080*3
            for i,t in enumerate(targets):
                buf=bytearray()
                while len(buf)<size:
                    part=proc.stdout.read(size-len(buf))
                    if not part:break
                    buf.extend(part)
                if len(buf)!=size:raise RuntimeError("INCOMPLETE_SPOT_SCAN_FRAME_"+str(i))
                frame=np.frombuffer(buf,dtype=np.uint8).reshape(1080,1920,3)
                label=classify(frame,functions);totals[label]+=1
                if label=="unknown":unknown.append((t,frame.copy()))
                if (i+1)%100==0:
                    print("RG895QA|SCENE_SAMPLE_PROGRESS|"+str(i+1)+"/"+str(len(targets))+"|UNKNOWN="+str(len(unknown)),flush=True)
            if proc.wait(timeout=60)!=0:
                err.seek(0)
                raise RuntimeError("SPOT_SCAN_FFMPEG_FAILED:"+err.read()[-400:].decode(errors="replace"))
        finally:
            if proc.poll() is None:proc.kill()
            proc.stdout.close()
    # Temporal stratification in each 10-min zone; no unknown points dropped from manifest.
    chosen=[]
    for zone in range(int(duration//600)+1):
        candidates=[(t,f) for t,f in unknown if int(t//600)==zone]
        if not candidates:continue
        for j in range(min(3,len(candidates))):
            index=round((j+.5)*(len(candidates)/min(3,len(candidates)))-.5)
            t,frame=candidates[min(max(index,0),len(candidates)-1)]
            chosen.append((t,frame))
    chosen=sorted(chosen,key=lambda z:z[0])
    for start in range(0,len(chosen),24):
        page=start//24+1
        subset=chosen[start:start+24]
        sheetcards=[dict(frame=f,caption=f"UNKNOWN {int(t)//3600:02d}:{int(t)//60%60:02d}:{int(t)%60:02d} | source sample") for t,f in subset]
        outfile=OUT/f"895_unknown_layout_samples_part_{page:02d}.jpg"
        make_sheet(sheetcards,outfile)
        print("RG895QA|UNKNOWN_SHEET|"+str(outfile),flush=True)
    manifest={"schema":"RG895_NOTIFICATION_EDIT_REVIEW_V93",
        "stream":"895","source_video":str(src),"duration_seconds":duration,
        "sample_stride_seconds":10,"spot_sampled_frames":len(targets),
        "layout_counts_10s_spot_check":totals,
        "unclassified_sample_times":[t for t,_ in unknown],
        "review_sheet_unknown_selected_times":[t for t,_ in chosen],
        "rejected_candidates":notes,
        "previous_scan_sampled_frames":23188,"previous_scan_unknown_layout_frames":1263,
        "already_auto_accepted_masks":20,
        "notification_coverage_verified":False,"publish_ready":False,
        "explicit_warning":"Source-wide coverage NOT certified; selected frames for manual review only"}
    (OUT/"895_review_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print("RG895QA|UNKNOWN_SAMPLED|"+str(totals["unknown"])+"|TOTAL|"+str(len(targets)),flush=True)
    print("RG895QA|LAYOUT_COUNTS|"+json.dumps(totals),flush=True)
    print("RG895QA|UNKNOWN_REVIEW_EXAMPLES|"+str(len(chosen)),flush=True)
    print("RG895QA|MANIFEST|"+str(OUT/"895_review_manifest.json"),flush=True)
    print("RG895QA|PRODUCTION_STATUS_AND_PLAN_UNTOUCHED|PASS",flush=True)
if __name__=="__main__":main()
