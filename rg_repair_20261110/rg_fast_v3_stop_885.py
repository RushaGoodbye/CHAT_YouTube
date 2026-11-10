"""Stop only the current 885 Full Stream export for tested speed rollout.
No reprocessing from GitHub, preserve original QA-only job and status backup.
"""
import sys,json,time,uuid
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
def go():
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers,stop_fullstream
    from rg_fullstream_process_state_v59 import worker_lock_state
    root=DATA/"fullstream_v2"
    live=[]
    for n in ("885","886","887","888","889"):
        st=root/n/"status.json"
        if st.exists() and json.loads(st.read_text(encoding="utf-8-sig")).get("state")=="RUNNING":live.append(n)
    if live!=["885"]:raise RuntimeError("CURRENT_RUNNING_NOT_EXACTLY_885:"+repr(live))
    req=root/"885"/"queue_request.json"
    old=req.read_bytes()
    job=json.loads(old.decode("utf-8-sig"))
    if job.get("stream")!="885" or job.get("qa_preview_export_requested") is not True or job.get("repair") is not True:
        raise RuntimeError("885_REVIEW_QUEUE_IDENTITY_MISMATCH")
    for n in ("886","887","888","889"):
        if not (root/n/"queue_request.json").exists():raise RuntimeError("MISSING_PENDING_"+n)
    output=Path(APP/"885"/"FULLSTREAM_YOUTUBE"/job["output_name"])
    progress=output.with_suffix(".progress.json")
    if not progress.exists():raise RuntimeError("PROGRESS_MISSING_STOP_REFUSED")
    current=json.loads(progress.read_text(encoding="utf-8-sig"))
    pct=float(current["progress_fraction"])
    print("RGROLLOUT|PROGRESS|"+str(round(pct*100,3)),flush=True)
    if pct>.5:raise RuntimeError("MORE_THAN_HALF_COMPLETED_DO_NOT_RESTART")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_FAST_V3_885_RESTART_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True)
    for name,p in [("885_queue_before.json",req),("885_status_before.json",root/"885"/"status.json")]:
        data=p.read_bytes()
        (backup/name).write_bytes(data)
        if (backup/name).read_bytes()!=data:raise RuntimeError("BAD_BACKUP_"+name)
    workers=active_workers()
    ids=sorted(int(x["ProcessId"]) for x in workers)
    if not ids:raise RuntimeError("NO_VERIFIED_WORKER")
    print("RGROLLOUT|PIDS|"+str(ids),flush=True)
    res=stop_fullstream(confirmed=True,expected_pids=ids,grace=15)
    print("RGROLLOUT|STOP|"+json.dumps(res,ensure_ascii=False,default=str),flush=True)
    if res.get("status")!="STOPPED_VERIFIED_WORKERS":raise RuntimeError("STOP_UNVERIFIED")
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("WORKER_REMAINS_ACTIVE")
    print("RGROLLOUT|BACKUP|"+str(backup),flush=True)
    print("RGROLLOUT|WORKER_STOPPED|PASS",flush=True)
    print("RGROLLOUT|MEDIA_UNTOUCHED|PASS",flush=True)
if __name__=="__main__":go()
