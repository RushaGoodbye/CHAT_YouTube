"""Stage manually visually verified "БАРС" alert blur for RG895, with rollback.

Visual evidence: uploaded seven-ROI contact sheet frame #5/#6 at 5490s,
the same alert. The source video is confirmed present from ~5488 to 5500,
absent at 5486 and 5502. Use padded [5486.5,5502.5].
The manual mask x848,y606,w506,h205 is restricted to V1 framed host
notification ROI (828,494)-(1400,835), covering entire alert.
Does NOT imply full source notification coverage or QA approval.
"""
from pathlib import Path
import sys,json,os,hashlib,uuid,time
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=DATA/"fullstream_v2"/"895"
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    sys.path.insert(0,str(APP))
    from rg_fullstream_auto_v2 import verified_popups
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_VIDEO_WORKER_NO_PATCH")
    statuspath=ROOT/"status.json"
    planpath=ROOT/"processing_plan.json"
    configpath=ROOT/"plan.json"
    evidencepath=ROOT/"NOTIFICATION_QA_V93"/"895_bars_notification_mask_v1.json"
    status=json.loads(statuspath.read_text(encoding="utf-8-sig"))
    existing=json.loads(planpath.read_text(encoding="utf-8-sig"))
    if status.get("state")!="PAUSED_EDITORIAL_QA":raise RuntimeError("895_NOT_QA_PAUSED")
    if existing.get("popup_coverage_verified") is not False:raise RuntimeError("QA_UNEXPECTED_APPROVED")
    if len(existing.get("popup_masks") or [])!=20:raise RuntimeError("AUTO_MASK_COUNT_CHANGED")
    if configpath.exists() or evidencepath.exists():raise RuntimeError("STAGED_CONFIG_ALREADY_PRESENT")
    mask={"x":848,"y":606,"width":506,"height":205,
          "layout":"framed_host","layout_verified":True,"editor_confirmed":True,
          "intervals":[[5486.5,5502.5]],
          "source":"manual_editorial_visual_review_RG895_BARS_ALERT",
          "evidence":"895_seven_suspect_rois.jpg;895_bars_notification_timing_5472_5502.jpg"}
    accepted,flags=verified_popups({"popup_masks":[mask]})
    if len(accepted)!=1:raise RuntimeError("MANUAL_ALERT_MASK_REJECTED:"+str(flags))
    for old in existing["popup_masks"]:
        for start,end in old.get("intervals",[]):
            if float(start)<5502.5 and float(end)>5486.5:raise RuntimeError("OVERLAP_WITH_EXISTING_AUTO_MASK")
    review=json.loads((ROOT/"NOTIFICATION_QA_V93"/"895_visual_review_verdict_v1.json").read_text(encoding="utf-8-sig"))
    if sorted(x["candidate_index"] for x in review["rejected_candidate_decisions"])!=[12,18,19]:
        raise RuntimeError("FALSE_REJECTIONS_NOT_REVIEWED")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG895_BARS_POPUP_MASK_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True,exist_ok=False)
    (backup/"895_status_before.json").write_bytes(statuspath.read_bytes())
    (backup/"895_processing_plan_before.json").write_bytes(planpath.read_bytes())
    sha_before={p.name:digest(p) for p in (statuspath,planpath)}
    config={"popup_masks":[mask],
        "popup_coverage_verified":False,
        "notification_qa_pending":True,
        "manual_mask_editor_review":"RG895_BARS_ALERT_5488_5500",
        "source_video":existing["video"],
        "source_duration_seconds":existing["duration_seconds"]}
    evidence={"schema":"RG895_BARS_ALERT_EDITORIAL_MASK_V1",
      "source_video":existing["video"],"stream":"895","manual_mask":mask,
      "true_notification_at_source_second":5490,
      "temporal_presence_sampled_at":[5488,5490,5492,5494,5496,5498,5500],
      "temporal_absence_sampled_at":[5486,5502],
      "number_of_prior_valid_automasks":20,
      "expected_total_masks_next_studio_build":21,
      "true_source_wide_popup_coverage_verified":False,
      "publish_ready":False,"studio_queue_not_started":True,
      "qa_status":"EDITOR_VERIFIED_ONE_ALERT_PENDING_STUDIO_REBUILD"}
    def atomic(p,data):
        tmp=p.with_name(p.name+"."+uuid.uuid4().hex[:7]+".tmp")
        try:
            tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
            os.replace(tmp,p)
        finally:tmp.unlink(missing_ok=True)
    try:
        atomic(evidencepath,evidence)
        atomic(configpath,config)
        a,f=verified_popups(json.loads(configpath.read_text(encoding="utf-8-sig")))
        if len(a)!=1:raise RuntimeError("POSTSTAGE_MASK_NOT_ACCEPTED")
        if any(digest(p)!=sha_before[p.name] for p in (statuspath,planpath)):
            raise RuntimeError("EXISTING_STATUS_OR_PLAN_MUTATED")
        if active_workers() or worker_lock_state(DATA)!="IDLE":
            raise RuntimeError("WORKER_STARTED_AFTER_STAGE_ABORT")
    except:
        evidencepath.unlink(missing_ok=True)
        configpath.unlink(missing_ok=True)
        print("RG895BARS|ROLLBACK|ATTEMPTED",flush=True)
        raise
    print("RG895BARS|MANUAL_VISUAL_ALERT_STAGED|PASS",flush=True)
    print("RG895BARS|MASK_BOUNDS|848,606,506,205|TIME|5486.5-5502.5",flush=True)
    print("RG895BARS|EXPECTED_AFTER_STUDIO_REBUILD|21",flush=True)
    print("RG895BARS|STATUS|PAUSED_EDITORIAL_QA|UNVERIFIED_COVERAGE",flush=True)
    print("RG895BARS|BACKUP|"+str(backup),flush=True)
    print("RG895BARS|CONFIG|"+str(configpath),flush=True)
    print("RG895BARS|NO_MP4_ASR_OR_QUEUE_CHANGED|PASS",flush=True)
if __name__=="__main__":main()
