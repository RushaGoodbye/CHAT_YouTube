"""RG 885 deterministic notification scan diagnostic: no media writes or QA bypass.
Converts 22 signed popup-checkpoint results into exact segment review priorities.
"""
from pathlib import Path
import json,re,math,os,sys,uuid,time
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\885")
CK=DATA/"popup_checkpoint_v89"
REGEX=re.compile(r"POPUP_LAYOUT_VALID_SAMPLES_(\d+)_OF_(\d+)")
def out(*s):print("RGPOPQA|"+"|".join(map(str,s)),flush=True)
def run():
    st=json.loads((DATA/"status.json").read_text(encoding="utf-8-sig"))
    if st.get("state")!="PAUSED_EDITORIAL_QA":
        raise RuntimeError("NOT_PAUSED_NO_REVIEW_PACK")
    if "NOTIFICATION_COVERAGE_UNVERIFIED" not in st.get("blocking_reasons",[]):
        raise RuntimeError("BLOCK_REASON_CHANGED")
    files=sorted(CK.glob("v89_popup_segment_*.json"))
    if len(files)!=22:raise RuntimeError("CHECKPOINT_SEGMENTS_NOT_22")
    rows=[]
    total_unknown=total_scanned=0
    for i,file in enumerate(files):
        if file.stem!=f"v89_popup_segment_{i:03d}":raise RuntimeError("CHECKPOINT_INDEX_GAP")
        item=json.loads(file.read_text(encoding="utf-8-sig"))
        if item.get("complete") is not True:raise RuntimeError("INCOMPLETE_CHECKPOINT:"+file.name)
        flags=item["result"].get("flags",[])
        matches=[REGEX.fullmatch(x) for x in flags]
        matches=[x for x in matches if x]
        if len(matches)!=1:raise RuntimeError("LAYOUT_FLAG_AMBIGUOUS:"+file.name)
        valid,scanned=map(int,matches[0].groups())
        if scanned<valid:raise RuntimeError("INVALID_COUNTS")
        unknown=scanned-valid
        total_unknown+=unknown;total_scanned+=scanned
        begin=600*i
        end=min(13057.023979,begin+606)
        if end<=begin:raise RuntimeError("INVALID_TIME_WINDOW")
        rows.append({"segment":i,"source_start_seconds":begin,
                     "source_end_seconds":round(end,3),
                     "sampled_frames":scanned,"unknown_layout_frames":unknown,
                     "unknown_percent":round(100*unknown/max(scanned,1),1),
                     "detected_popup_candidates":len(item["result"].get("masks",[])),
                     "review_priority":("HIGH" if unknown/scanned>=.1 else "MEDIUM" if unknown>0 else "LOW"),
                     "sample_seek_seconds":[round(begin+(end-begin)*fraction,2) for fraction in (.15,.5,.85)]})
    hot=sorted((x for x in rows if x["unknown_layout_frames"]>0),
               key=lambda x:(-x["unknown_layout_frames"],x["segment"]))
    report={"schema":"RG_POPUP_QA_REVIEW_V1","stream":"885",
            "source_media_untouched":True,"worker_launched":False,"qa_bypass":False,
            "source_scanned_by_existing_v89":True,
            "cached_checkpoints":len(files),
            "counts_include_chunk_overlap":True,
            "sampled_frames_with_overlap":total_scanned,
            "unrecognized_layout_frames_with_overlap":total_unknown,
            "mandatory_human_visual_qa":True,
            "status":"NOTIFICATION_COVERAGE_UNVERIFIED",
            "unknown_layout_hotspots":hot,
            "all_segments":rows,
            "automated_coverage_certified":False,
            "note":"Source-time regions needing additional visual verification; these are interval priorities, not precise per-frame unknown coordinates"}
    target=DATA/"notification_qa_review_v1.json"
    if target.exists():
        previous=json.loads(target.read_text(encoding="utf-8-sig"))
        if previous.get("schema")!="RG_POPUP_QA_REVIEW_V1":raise RuntimeError("EXISTING_REPORT_UNRELATED")
    temp=target.with_name(target.name+"."+uuid.uuid4().hex+".tmp")
    try:
        temp.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        os.replace(temp,target)
    finally:
        temp.unlink(missing_ok=True)
    out("REPORT",target)
    out("SEGMENTS",len(rows),"UNRECOGNIZED",total_unknown,"SAMPLES",total_scanned)
    for item in hot[:12]:
        out("HOTSPOT",item["segment"],item["source_start_seconds"],item["source_end_seconds"],
            "UNKNOWN",item["unknown_layout_frames"],"PERCENT",item["unknown_percent"])
    out("PASS","EVIDENCE_PACK_WRITTEN","QA_BLOCK_RETAINED")
if __name__=="__main__":run()
