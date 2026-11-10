"""Arm stream 885 for QA-only review MP4, without worker launch or false QA pass.
Source and all unrelated queue requests remain unchanged.
"""
from pathlib import Path
import json,sys,time,uuid,os,argparse
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
def atomic(path,row):
    temp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        temp.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)
def main():
    sys.path.insert(0,str(APP))
    from rg_fullstream_qa_export_v96 import evaluate
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    from rg_fullstream_launcher_v2 import output_for_request
    base=DATA/"fullstream_v2"
    jobdir=base/"885"
    q=jobdir/"queue_request.json";status=jobdir/"status.json"
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_PROCESSING_NO_QUEUE_CHANGE")
    all_jobs=[]
    for f in base.glob("*/queue_request.json"):
        d=json.loads(f.read_text(encoding="utf-8-sig"))
        if d.get("stream")!=f.parent.name:raise RuntimeError("QUEUE_IDENTITY_NOT_MATCHED")
        all_jobs.append(f.parent.name)
    if sorted(all_jobs)!=["885","886","887","888","889"]:
        raise RuntimeError("UNEXPECTED_QUEUE_"+repr(all_jobs))
    oldq=q.read_bytes();olds=status.read_bytes()
    row=json.loads(oldq.decode("utf-8-sig"));st=json.loads(olds.decode("utf-8-sig"))
    if st.get("state")!="PAUSED_EDITORIAL_QA":
        raise RuntimeError("885_NOT_PAUSED")
    if row.get("repair") is True or row.get("qa_preview_export_requested") is True:
        raise RuntimeError("885_ALREADY_REVIEW_OR_REPAIR_REQUEST")
    plan=json.loads((jobdir/"processing_plan.json").read_text(encoding="utf-8-sig"))
    gate=json.loads((jobdir/"editorial_preflight_v82.json").read_text(encoding="utf-8-sig"))
    if gate.get("blocking_reasons")!=["NOTIFICATION_COVERAGE_UNVERIFIED"]:
        raise RuntimeError("UNEXPECTED_QA_BLOCKERS")
    plan["qa_preview_export_requested"]=True
    plan["overnight_queue_sequential"]=True
    admission=evaluate(plan,gate)
    if not admission.get("allow_review_render") or admission.get("publish_ready") is not False:
        raise RuntimeError("REVIEW_RENDER_NOT_ADMITTED:"+repr(admission))
    stamp=time.strftime("%Y%m%dT%H%M%S",time.gmtime())
    output_name=f"RG_885_FULL_YOUTUBE_CENSOR_RECHECK_V55_{stamp}_{uuid.uuid4().hex[:8]}.mp4"
    newrow=dict(row,repair=True,output_name=output_name,
                qa_preview_export_requested=True,qa_review_only=True,
                qa_publication_allowed=False)
    output=output_for_request("885",newrow,APP)
    if output.exists():raise RuntimeError("OUTPUT_ALREADY_EXISTS")
    # Archive exact bytes to allow point-in-time rollback while idle
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_885_QA_REVIEW_V97_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True)
    (backup/"queue_request.original.json").write_bytes(oldq)
    (backup/"status.original.json").write_bytes(olds)
    if (backup/"queue_request.original.json").read_bytes()!=oldq or (backup/"status.original.json").read_bytes()!=olds:
        raise RuntimeError("BACKUP_VERIFICATION_FAILED")
    newstatus=dict(state="QUEUED",stream="885",repair=True,
                   qa_preview_export_requested=True,qa_only=True,
                   output=str(output),queued_at=row["created_utc_epoch"],
                   editorial_approval=False,publish_ready=False,
                   qa_unresolved=["NOTIFICATION_COVERAGE_UNVERIFIED"])
    try:
        if active_workers() or worker_lock_state(DATA)!="IDLE":
            raise RuntimeError("WORKER_BECAME_ACTIVE")
        if q.read_bytes()!=oldq or status.read_bytes()!=olds:
            raise RuntimeError("CONCURRENT_JOB_CHANGE")
        atomic(q,newrow)
        atomic(status,newstatus)
        check=json.loads(q.read_text(encoding="utf-8-sig"))
        actual=json.loads(status.read_text(encoding="utf-8-sig"))
        if (check.get("qa_preview_export_requested") is not True
            or check.get("repair") is not True
            or actual.get("publish_ready") is not False
            or actual.get("state")!="QUEUED"):
            raise RuntimeError("POSTUPDATE_VERIFICATION_FAILED")
        for id in range(886,890):
            r=json.loads((base/str(id)/"queue_request.json").read_text(encoding="utf-8-sig"))
            if r.get("stream")!=str(id):raise RuntimeError("OTHER_QUEUE_CHANGED")
        print("RG885REVIEW|ARMED|PASS",flush=True)
        print("RG885REVIEW|OUTPUT|"+str(output),flush=True)
        print("RG885REVIEW|QA_ONLY|TRUE|PUBLICATION|BLOCKED",flush=True)
        print("RG885REVIEW|BACKUP|"+str(backup),flush=True)
        print("RG885REVIEW|WORKER_STARTED|FALSE",flush=True)
    except BaseException:
        if not active_workers():
            q.write_bytes(oldq);status.write_bytes(olds)
            print("RG885REVIEW|ROLLBACK|RESTORED",flush=True)
        raise
if __name__=="__main__":main()
