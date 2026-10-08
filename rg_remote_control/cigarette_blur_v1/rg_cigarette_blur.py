#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from rg_privacy_coverage_qa import evaluate as evaluate_coverage

VERSION="RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2"
TICKS_PER_SECOND=254016000000

def _read_json(path,default=None):
    try:return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:return {} if default is None else default

def _merge_ranges(rows,gap=0.35):
    vals=[]
    for r in rows or []:
        try:
            a=float(r.get("source_start_sec",r.get("start")))
            b=float(r.get("source_end_sec",r.get("end")))
        except Exception:continue
        if b>a:vals.append([a,b])
    vals.sort();out=[]
    for a,b in vals:
        if not out or a>out[-1][1]+gap:out.append([a,b])
        else:out[-1][1]=max(out[-1][1],b)
    return out

def _iou(a,b):
    ax0,ay0,ax1,ay1=map(float,a); bx0,by0,bx1,by1=map(float,b)
    ix0=max(ax0,bx0);iy0=max(ay0,by0);ix1=min(ax1,bx1);iy1=min(ay1,by1)
    iw=max(0.0,ix1-ix0);ih=max(0.0,iy1-iy0);inter=iw*ih
    aa=max(0.0,ax1-ax0)*max(0.0,ay1-ay0);bb=max(0.0,bx1-bx0)*max(0.0,by1-by0)
    return inter/max(1e-9,aa+bb-inter)

def _center(box):
    x0,y0,x1,y1=map(float,box)
    return ((x0+x1)*0.5,(y0+y1)*0.5)

def _associate_tracks(frames,opts):
    max_gap=float(opts.get("track_max_gap_sec",0.65))
    max_dist=float(opts.get("track_max_center_distance",4.2))
    tracks=[];next_id=1
    for fr in sorted(frames or [],key=lambda x:float(x.get("t",0))):
        t=float(fr.get("t",0)); boxes=sorted(fr.get("boxes") or [],key=lambda x:float(x.get("score",0)),reverse=True)
        used=set()
        for box in boxes:
            bb=box.get("bbox") or []
            if len(bb)!=4:continue
            cx,cy=_center(bb);bw=max(2.0,float(bb[2]-bb[0]));bh=max(2.0,float(bb[3]-bb[1]))
            best=None;best_cost=1e9
            for tr in tracks:
                if tr["id"] in used or not tr["hits"]:continue
                last=tr["hits"][-1];gap=t-float(last["t"])
                if gap< -1e-6 or gap>max_gap:continue
                lb=last["bbox"];lx,ly=_center(lb)
                scale=max(28.0,math.sqrt(max(4.0,bw*bh)),math.sqrt(max(4.0,(lb[2]-lb[0])*(lb[3]-lb[1]))))
                dist=math.hypot(cx-lx,cy-ly)/scale
                ov=_iou(bb,lb)
                cost=dist+0.35*(1.0-ov)
                if cost<best_cost and dist<=max_dist:
                    best=tr;best_cost=cost
            hit={"t":t,"bbox":[int(v) for v in bb],"score":float(box.get("score",0)),"class":box.get("class")}
            if best is None:
                best={"id":next_id,"hits":[]};next_id+=1;tracks.append(best)
            best["hits"].append(hit);used.add(best["id"])
    return tracks

def _pad_bbox(bb,opts,frame_w=1920,frame_h=1080):
    x0,y0,x1,y1=map(float,bb);w=max(1.0,x1-x0);h=max(1.0,y1-y0)
    px=max(float(opts.get("bbox_padding_px",18)),w*float(opts.get("bbox_padding_ratio",0.35)))
    py=max(float(opts.get("bbox_padding_px",18)),h*float(opts.get("bbox_padding_ratio",0.35)))
    return [
        max(0,int(math.floor(x0-px))),max(0,int(math.floor(y0-py))),
        min(frame_w,int(math.ceil(x1+px))),min(frame_h,int(math.ceil(y1+py))),
    ]

def _interp(a,b,f):
    return [float(a[i])+(float(b[i])-float(a[i]))*f for i in range(4)]

def _track_intervals(track,opts,ranges):
    hits=sorted(track["hits"],key=lambda x:x["t"])
    if not hits:return []
    step=1.0/max(2.0,float(opts.get("slice_fps",10.0)))
    max_gap=float(opts.get("track_max_gap_sec",0.65))
    start_pad=float(opts.get("start_pad_sec",0.12))
    end_hold=float(opts.get("end_hold_sec",0.22))
    rows=[]
    def add(a,b,bb):
        if b<=a:return
        for ra,rb in ranges:
            x=max(a,ra);y=min(b,rb)
            if y>x:
                rows.append({"source_start_sec":round(x,5),"source_end_sec":round(y,5),
                             "bbox":_pad_bbox(bb,opts),"kind":"CIGARETTE","track_id":track["id"]})
    if len(hits)==1:
        add(hits[0]["t"]-start_pad,hits[0]["t"]+end_hold,hits[0]["bbox"])
        return rows
    add(hits[0]["t"]-start_pad,hits[0]["t"],hits[0]["bbox"])
    for left,right in zip(hits,hits[1:]):
        t0=float(left["t"]);t1=float(right["t"]);gap=t1-t0
        if gap<=0:continue
        if gap>max_gap:
            add(t0,t0+end_hold,left["bbox"])
            add(t1-start_pad,t1,right["bbox"])
            continue
        n=max(1,int(math.ceil(gap/step)))
        for j in range(n):
            a=t0+gap*j/n;b=t0+gap*(j+1)/n
            mid=(j+0.5)/n
            add(a,b,_interp(left["bbox"],right["bbox"],mid))
    add(hits[-1]["t"],hits[-1]["t"]+end_hold,hits[-1]["bbox"])
    return rows

def _confirm_tracks(tracks,opts,ranges):
    accepted=[];rejected=[]
    min_hits=max(1,int(opts.get("min_track_hits",2)))
    strong=float(opts.get("single_hit_strong_confidence",0.34))
    min_span=float(opts.get("min_track_span_sec",0.10))
    confidence=float(opts.get("confidence",0.08))
    short_min_span=float(opts.get("short_stable_min_span_sec",0.05))
    short_max_gap=float(opts.get("short_stable_max_gap_sec",0.12))
    short_min_iou=float(opts.get("short_stable_min_iou",0.72))
    for tr in tracks:
        hits=tr["hits"];span=(hits[-1]["t"]-hits[0]["t"]) if len(hits)>1 else 0.0
        scores=[float(x.get("score",0)) for x in hits]
        max_score=max(scores+[0.0])
        normal_track=(len(hits)>=min_hits and span>=min_span)
        strong_hit=max_score>=strong
        short_stable=False
        if len(hits)>=min_hits and len(hits)>=2 and short_min_span<=span<min_span:
            gaps=[float(b["t"])-float(a["t"]) for a,b in zip(hits,hits[1:])]
            ious=[_iou(a.get("bbox") or [0,0,0,0],b.get("bbox") or [0,0,0,0]) for a,b in zip(hits,hits[1:])]
            classes=[str(x.get("class") or "") for x in hits]
            short_stable=(
                bool(gaps) and max(gaps)<=short_max_gap and
                bool(ious) and min(ious)>=short_min_iou and
                min(scores or [0.0])>=confidence and
                len(set(classes))==1 and bool(classes[0])
            )
        ok=normal_track or strong_hit or short_stable
        tr["span_sec"]=round(span,4);tr["max_score"]=round(max_score,4)
        if short_stable:tr["confirmation"]="SHORT_STABLE"
        elif normal_track:tr["confirmation"]="NORMAL_TRACK"
        elif strong_hit:tr["confirmation"]="STRONG_HIT"
        if ok:
            tr["intervals"]=_track_intervals(tr,opts,ranges);accepted.append(tr)
        else:rejected.append(tr)
    return accepted,rejected

def scan_cigarettes(video_path,source_ranges,opts=None,progress_cb=None):
    opts=dict(opts or {})
    data=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
    app=Path(__file__).resolve().parent
    runtime=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
    manifest=_read_json(data/"cigarette_detector_v1.json",{})
    site=Path(manifest.get("worker_site") or data/"workers"/"cigarette_blur"/"site")
    model=Path(manifest.get("model") or data/"models"/"cigarette_blur"/"yolov8s-worldv2.pt")
    worker=app/"rg_cigarette_detector_worker.py"
    if not runtime.is_file() or not worker.is_file() or not site.is_dir() or not model.is_file():
        raise RuntimeError("Mandatory cigarette detector is not ready")
    ranges=_merge_ranges(source_ranges,gap=float(opts.get("range_merge_gap_sec",0.35)))
    if not ranges:
        return {"version":VERSION,"passed":True,"enabled":True,"mandatory":True,
                "intervals":[],"tracks":[],"raw_detection_count":0,"status":"NO_RANGES"}
    payload={"video":str(video_path),"ranges":[{"start":a,"end":b} for a,b in ranges],
             "opts":opts,"model":str(model)}
    with tempfile.TemporaryDirectory(prefix="rg_cigarette_") as td:
        inp=Path(td)/"in.json";outp=Path(td)/"out.json"
        inp.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
        env=os.environ.copy()
        env["PYTHONUTF8"]="1";env["PYTHONIOENCODING"]="utf-8"
        env["PYTHONPATH"]=str(site)+os.pathsep+str(app)
        env["YOLO_CONFIG_DIR"]=str(data/"models"/"cigarette_blur"/"config")
        proc=subprocess.Popen([str(runtime),"-u","-X","utf8",str(worker),"--input",str(inp),"--output",str(outp)],
                              cwd=str(app),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              text=True,encoding="utf-8",errors="replace",
                              creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        tail=[]
        assert proc.stdout is not None
        for raw in proc.stdout:
            line=raw.rstrip()
            tail.append(line);tail=tail[-80:]
            if line.startswith("RGCIGPROGRESS|") and progress_cb:
                try:
                    _,frac,phase=line.split("|",2);progress_cb(float(frac),phase)
                except Exception:pass
        rc=proc.wait()
        if rc!=0 or not outp.is_file():
            raise RuntimeError("Mandatory cigarette detector failed: "+"\n".join(tail[-20:]))
        raw=_read_json(outp,{})
    if not raw.get("passed"):
        raise RuntimeError("Mandatory cigarette detector did not pass")
    tracks=_associate_tracks(raw.get("frames") or [],opts)
    accepted,rejected=_confirm_tracks(tracks,opts,ranges)
    intervals=[]
    for tr in accepted:
        intervals.extend(tr.get("intervals") or [])
    if len(intervals)>int(opts.get("max_overlay_slices",6000)):
        raise RuntimeError("Cigarette tracking generated too many overlay slices")
    unconfirmed=sum(len(x.get("hits") or []) for x in rejected)
    report={
        "version":VERSION,"passed":not (raw.get("raw_detection_count",0) and not accepted),
        "enabled":True,"mandatory":True,"video":str(video_path),"detector":raw.get("version"),
        "model":raw.get("model"),"device":raw.get("device"),"cuda":raw.get("cuda"),
        "raw_detection_count":int(raw.get("raw_detection_count",0)),
        "confirmed_track_count":len(accepted),"rejected_track_count":len(rejected),
        "unconfirmed_detection_count":unconfirmed,"tracks":accepted,
        "rejected_tracks":rejected,"intervals":intervals,
        "interval_count":len(intervals),"video_decode_backends":raw.get("video_decode_backends") or [],
        "status":"TRACKED" if accepted else ("AMBIGUOUS" if raw.get("raw_detection_count",0) else "NO_CIGARETTE_DETECTED"),
    }
    if raw.get("raw_detection_count",0) and not accepted:
        report["failures"]=["UNCONFIRMED_CIGARETTE_DETECTIONS"]
    return report

def _intval(n,tag,default=0):
    try:return int(float(n.findtext(tag,str(default))))
    except Exception:return int(default)

def _txt(n,tag,default=""):
    x=n.find(tag)
    return default if x is None or x.text is None else x.text.strip()

def _add_blur(clip,radius):
    filt=ET.SubElement(clip,"filter");ET.SubElement(filt,"enabled").text="TRUE"
    ET.SubElement(filt,"start").text="-1";ET.SubElement(filt,"end").text="-1"
    eff=ET.SubElement(filt,"effect");ET.SubElement(eff,"name").text="Gaussian Blur"
    ET.SubElement(eff,"effectid").text="Gaussian Blur";ET.SubElement(eff,"effecttype").text="filter"
    ET.SubElement(eff,"mediatype").text="video"
    p=ET.SubElement(eff,"parameter");ET.SubElement(p,"parameterid").text="channel";ET.SubElement(p,"name").text="Channel";ET.SubElement(p,"value").text="1"
    p=ET.SubElement(eff,"parameter");ET.SubElement(p,"parameterid").text="radius";ET.SubElement(p,"name").text="Radius"
    ET.SubElement(p,"valuemin").text="0";ET.SubElement(p,"valuemax").text="100";ET.SubElement(p,"value").text=str(float(radius))

def _add_crop(clip,bbox,frame_w=1920,frame_h=1080):
    x0,y0,x1,y1=map(float,bbox)
    vals=(("left",100*x0/frame_w),("right",100*max(0,frame_w-x1)/frame_w),
          ("top",100*y0/frame_h),("bottom",100*max(0,frame_h-y1)/frame_h))
    filt=ET.SubElement(clip,"filter");ET.SubElement(filt,"enabled").text="TRUE"
    ET.SubElement(filt,"start").text="-1";ET.SubElement(filt,"end").text="-1"
    eff=ET.SubElement(filt,"effect");ET.SubElement(eff,"name").text="Crop";ET.SubElement(eff,"effectid").text="crop"
    ET.SubElement(eff,"effecttype").text="motion";ET.SubElement(eff,"mediatype").text="video";ET.SubElement(eff,"effectcategory").text="motion"
    for pid,val in vals:
        p=ET.SubElement(eff,"parameter");ET.SubElement(p,"name").text=pid;ET.SubElement(p,"parameterid").text=pid
        ET.SubElement(p,"value").text=f"{val:.6f}";ET.SubElement(p,"valuemin").text="0";ET.SubElement(p,"valuemax").text="100"

def _slim_file_ref(clip):
    f=clip.find("file")
    if f is None:return
    fid=f.get("id","file-video")
    for ch in list(f):f.remove(ch)
    f.attrib.clear();f.set("id",fid)

def _piece(src,tl0,tl1,bbox,fps,idx,opts):
    new=copy.deepcopy(src);new.set("id",f"rg-cigarette-{idx}")
    old_start=_intval(src,"start",0);old_in=_intval(src,"in",0)
    delta=int(tl0)-old_start;dur=int(tl1)-int(tl0)
    for tag,val in (("start",tl0),("end",tl1),("in",old_in+delta),("out",old_in+delta+dur)):
        n=new.find(tag)
        if n is not None:n.text=str(int(val))
    pin=(old_in+delta)/float(fps);pout=(old_in+delta+dur)/float(fps)
    if new.find("pproTicksIn") is not None:new.find("pproTicksIn").text=str(int(round(pin*TICKS_PER_SECOND)))
    if new.find("pproTicksOut") is not None:new.find("pproTicksOut").text=str(int(round(pout*TICKS_PER_SECOND)))
    for lk in list(new.findall("link")):new.remove(lk)
    # Blur/Crop must happen in source coordinates before the copied camera Motion filters.
    old_filters=list(new.findall("filter"))
    for f in old_filters:new.remove(f)
    for _ in range(max(1,int(opts.get("blur_passes",2)))):
        _add_blur(new,float(opts.get("blur_radius",62.0)))
    _add_crop(new,bbox,int(opts.get("frame_width",1920)),int(opts.get("frame_height",1080)))
    for f in old_filters:new.append(f)
    _slim_file_ref(new)
    return new

def _insert_before_state(track,clip):
    children=list(track);idx=len(children)
    for i,ch in enumerate(children):
        if ch.tag in ("enabled","locked"):idx=i;break
    track.insert(idx,clip)

def _active_close(close_clips,t):
    best=None
    for c in close_clips:
        a=_intval(c,"start")/30.0;b=_intval(c,"end")/30.0
        if a-1e-6<=t<b-1e-6:best=c
    return best

def inject_cigarette_blur(xml_path,detection_report,opts=None,fps=30):
    opts=dict(opts or {});xml_path=Path(xml_path)
    text=xml_path.read_text(encoding="utf-8")
    body=text.split("<!DOCTYPE xmeml>",1)[1].strip() if "<!DOCTYPE xmeml>" in text else text
    root=ET.fromstring(body);seq=root.find("sequence")
    if seq is None:raise RuntimeError("Cigarette Blur: sequence missing")
    video=seq.find("./media/video")
    if video is None:raise RuntimeError("Cigarette Blur: video missing")
    tracks=video.findall("track")
    if not tracks:raise RuntimeError("Cigarette Blur: no video tracks")
    base_track=tracks[0];close=[]
    for tr in tracks[1:]:
        close.extend([c for c in tr.findall("clipitem") if c.get("id","").startswith("rg-close-")])
    # Remove stale cigarette tracks from retries.
    for tr in list(video.findall("track")):
        if any(c.get("id","").startswith("rg-cigarette-") for c in tr.findall("clipitem")):
            video.remove(tr)
    expected=[];frame_w=int(opts.get("frame_width",1920))
    for det in (detection_report or {}).get("intervals") or []:
        ds0=float(det["source_start_sec"]);ds1=float(det["source_end_sec"]);bbox=det["bbox"]
        center_x=(float(bbox[0])+float(bbox[2]))*0.5
        for base in base_track.findall("clipitem"):
            name=_txt(base,"name","").lower()
            if not name.endswith((".mp4",".mov",".mxf",".avi",".mkv")):continue
            if any(x in name for x in ("дисклеймер","пекшот","packshot","coda","подложка")):continue
            src0=_intval(base,"in")/float(fps);src1=_intval(base,"out")/float(fps)
            ov0=max(ds0,src0);ov1=min(ds1,src1)
            if ov1<=ov0:continue
            tl_base=_intval(base,"start")/float(fps)
            ta=tl_base+(ov0-src0);tb=tl_base+(ov1-src0)
            boundaries={ta,tb}
            for cc in close:
                ca=_intval(cc,"start")/float(fps);cb=_intval(cc,"end")/float(fps)
                if ta<ca<tb:boundaries.add(ca)
                if ta<cb<tb:boundaries.add(cb)
            bs=sorted(boundaries)
            for a,b in zip(bs,bs[1:]):
                if b-a<1.0/fps:continue
                mid=(a+b)*0.5;cc=_active_close(close,mid)
                if cc is not None:
                    # CLOSE_RIGHT hides the left half. Blur only if the cigarette is visible on the right.
                    if center_x<frame_w*0.5:continue
                    visible=cc
                else:visible=base
                expected.append({"clip":visible,"timeline_start_sec":a,"timeline_end_sec":b,
                                 "bbox":bbox,"kind":"CIGARETTE","source_id":det.get("track_id")})
    if not expected:
        # No cigarette is visible in retained final frames.
        qa={"version":VERSION,"passed":bool((detection_report or {}).get("passed",True)),
            "detected_interval_count":len((detection_report or {}).get("intervals") or []),
            "raw_detection_count":int((detection_report or {}).get("raw_detection_count",0)),
            "confirmed_track_count":int((detection_report or {}).get("confirmed_track_count",0)),
            "overlay_count":0,"expected_overlay_count":0,"expected_overlay_sec":0.0,
            "failures":list((detection_report or {}).get("failures") or []),
            "coverage_qa":evaluate_coverage([],[],fps=fps,tolerance_frames=1),
            "policy":"NO_VISIBLE_CIGARETTE_IN_RETAINED_FRAMES"}
        return qa
    tr=ET.SubElement(video,"track",{"TL.SQTrackShy":"0","TL.SQTrackExpandedHeight":"41","TL.SQTrackExpanded":"0","MZ.TrackTargeted":"0"})
    overlays=[]
    for idx,p in enumerate(expected,1):
        tl0=int(round(float(p["timeline_start_sec"])*fps));tl1=int(round(float(p["timeline_end_sec"])*fps))
        if tl1<=tl0:continue
        clip=_piece(p["clip"],tl0,tl1,p["bbox"],fps,idx,opts);_insert_before_state(tr,clip)
        overlays.append({"clip_id":clip.get("id"),"timeline_start_sec":tl0/float(fps),
                         "timeline_end_sec":tl1/float(fps),"bbox":[int(v) for v in p["bbox"]],
                         "kind":"CIGARETTE","source_detection":p.get("source_id")})
    ET.SubElement(tr,"enabled").text="TRUE";ET.SubElement(tr,"locked").text="FALSE"
    try:ET.indent(root,space="\t")
    except Exception:pass
    xml_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'+ET.tostring(root,encoding="unicode"),encoding="utf-8")
    structural=verify_cigarette_blur(xml_path,len(overlays))
    expected_rows=[{"timeline_start_sec":p["timeline_start_sec"],"timeline_end_sec":p["timeline_end_sec"],
                    "kind":"CIGARETTE","source_id":p.get("source_id")} for p in expected]
    coverage=evaluate_coverage(expected_rows,overlays,fps=fps,tolerance_frames=1)
    failures=list((detection_report or {}).get("failures") or [])+list(structural.get("failures") or [])+list(coverage.get("failures") or [])
    return {"version":VERSION,"passed":not failures,"failures":list(dict.fromkeys(failures)),
            "mandatory":True,"raw_detection_count":int((detection_report or {}).get("raw_detection_count",0)),
            "confirmed_track_count":int((detection_report or {}).get("confirmed_track_count",0)),
            "detected_interval_count":len((detection_report or {}).get("intervals") or []),
            "overlay_count":len(overlays),"expected_overlay_count":len(expected_rows),
            "expected_overlay_sec":round(sum(max(0,x["timeline_end_sec"]-x["timeline_start_sec"]) for x in expected_rows),3),
            "overlays":overlays,"expected_visible_windows":expected_rows,"coverage_qa":coverage,
            "policy":"MANDATORY_TRACKED_OBJECT_ONLY_CROP_GAUSSIAN_BLUR"}

def verify_cigarette_blur(xml_path,expected_count=None):
    text=Path(xml_path).read_text(encoding="utf-8")
    body=text.split("<!DOCTYPE xmeml>",1)[1].strip() if "<!DOCTYPE xmeml>" in text else text
    root=ET.fromstring(body)
    clips=[c for c in root.findall(".//clipitem") if c.get("id","").startswith("rg-cigarette-")]
    failures=[]
    for c in clips:
        eids=[_txt(f.find("effect"),"effectid","") if f.find("effect") is not None else "" for f in c.findall("filter")]
        if "crop" not in eids:failures.append(c.get("id","")+":CROP_MISSING")
        if "Gaussian Blur" not in eids:failures.append(c.get("id","")+":GAUSSIAN_BLUR_MISSING")
        if _intval(c,"end")<=_intval(c,"start"):failures.append(c.get("id","")+":INVALID_DURATION")
    if expected_count is not None and len(clips)!=int(expected_count):
        failures.append(f"OVERLAY_COUNT:{len(clips)}!={int(expected_count)}")
    return {"passed":not failures,"overlay_count":len(clips),"failures":failures}

def human_text(report,title="RG CIGARETTE BLUR"):
    lines=[title,"="*68,f"Version: {report.get('version',VERSION)}",
           f"Mandatory: YES",
           f"Raw detections: {report.get('raw_detection_count',0)}",
           f"Confirmed tracks: {report.get('confirmed_track_count',0)}",
           f"Tracked blur overlays: {report.get('overlay_count',0)}",
           f"QA: {'PASS' if report.get('passed') else 'FAIL'}"]
    cov=report.get("coverage_qa") or {}
    if cov:lines.append(f"Coverage: {100*float(cov.get('coverage_ratio',1.0)):.2f}%")
    for x in report.get("failures") or []:lines.append("- "+str(x))
    return "\n".join(lines)+"\n"
