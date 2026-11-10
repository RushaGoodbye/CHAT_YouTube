"""Create actionable, fail-closed notification QA case file for RG full streams.
Reads cached complete scan and V41 rejections; never approves coverage merely
because the scan finished. Does not alter queue, source, masks or export.
"""
from pathlib import Path
import json,hashlib,sys,os,uuid,argparse,time
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
def atomic_json(path,value):
    tmp=path.with_name(path.name+"."+uuid.uuid4().hex[:6]+".tmp")
    try:
        tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)
def make(root):
    root=Path(root)
    p=root/"processing_plan.json";s=root/"status.json";cache=root/"completed_popups_v76.json"
    source=json.loads(p.read_text(encoding="utf-8-sig"))
    status=json.loads(s.read_text(encoding="utf-8-sig"))
    raw=json.loads(cache.read_text(encoding="utf-8-sig"))["result"]
    evidence=json.loads((root/"editorial_evidence_v84.json").read_text(encoding="utf-8-sig"))
    reject_path=root/"V41_POPUP_VISUAL_REJECTIONS.json"
    rejects=json.loads(reject_path.read_text(encoding="utf-8-sig")) if reject_path.is_file() else []
    candidates=raw["masks"]
    duration=float(source["duration_seconds"])
    frames=evidence.get("popup_scan_coverage",{}).get("samples",[])
    unknown=sum(int(x.get("unknown_layout_frames",0)) for x in frames)
    total=sum(int(x.get("scanned_frames",0)) for x in frames)
    if status.get("state")!="PAUSED_EDITORIAL_QA" or source.get("popup_coverage_verified") is not False:
        raise RuntimeError("NOT_PAUSED_UNVERIFIED_QA_NO_EDIT")
    points=[]
    for item in rejects:
        idx=int(item["index"])
        if not 0<=idx<len(candidates):raise RuntimeError("BAD_REJECTION_INDEX")
        mask=candidates[idx]
        a,b=map(float,mask["intervals"][0])
        if not 0<=a<b<=duration:raise RuntimeError("BAD_REJECTION_TIME")
        points.append(dict(kind="REJECTED_VISUAL_CANDIDATE",candidate_index=idx,
             source_start_seconds=a,source_end_seconds=b,source_second=round((a+b)/2,2),
             rectangle=[int(mask[k]) for k in ("x","y","width","height")],
             layout=mask.get("layout"),status="REQUIRES_VISUAL_CONFIRMATION",
             reason=item.get("reason"),approved=False))
    samples_dir=root/"NOTIFICATION_QA_V93"
    sheet1=samples_dir/"895_three_rejected_candidates.jpg"
    sheet_files=[str(p) for p in sorted(samples_dir.glob("895_unknown_layout_samples_part_*.jpg"))] if samples_dir.is_dir() else []
    reviewed=dict(schema="RG_NOTIFICATION_QA_REVIEW_V93",stream=str(source["stream"]),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        exact_source=str(source["video"]),source_duration_seconds=duration,
        state="BLOCKED_REQUIRES_EDITORIAL_REVIEW",
        source_scan_completed=True,source_scan_sampled_frames=total,
        unclassified_source_samples=unknown,
        existing_automated_masks=len(source.get("popup_masks") or []),
        visual_rejection_count=len(points),
        review_items=points,
        review_images={"rejections":str(sheet1) if sheet1.is_file() else None,
                       "unknown_layout_pages":sheet_files},
        auto_approve=False,popup_coverage_verified=False,publish_ready=False,
        editor_approval_recorded=False,
        source_scan_is_not_source_wide_notification_certification=True,
        qa_blocking_reasons=status.get("blocking_reasons",[]),
        instruction="Confirm which rejected cards are real notifications and whether unknown layouts hide any notifications. Never publish while unverified.")
    target=root/"notification_qa_review_v93.json"
    atomic_json(target,reviewed)
    if len(points)!=len(rejects):raise RuntimeError("REVIEW_COUNT_MISMATCH")
    if reviewed["publish_ready"] or reviewed["popup_coverage_verified"]:raise RuntimeError("FALSE_QA_PASS")
    print("RG895REVIEW|STREAM|"+str(source["stream"]),flush=True)
    print("RG895REVIEW|REJECTED|"+str(len(points))+"|UNKNOWN|"+str(unknown)+"/"+str(total),flush=True)
    print("RG895REVIEW|REPORT|"+str(target),flush=True)
    print("RG895REVIEW|SHEETS|"+str(len(sheet_files))+"|REJECTED_SHEET|"+str(sheet1.is_file()),flush=True)
    print("RG895REVIEW|EXPLICIT_BLOCK_QA|PASS",flush=True)
    print("RG895REVIEW|NO_AUDIO_ASR_QUEUE_OR_VIDEO_CHANGES|PASS",flush=True)
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stream",help="3-5 digit stream number")
    a=parser.parse_args()
    if not a.stream.isdigit() or not 3<=len(a.stream)<=5:raise RuntimeError("INVALID_STREAM")
    make(DATA/"fullstream_v2"/a.stream)
