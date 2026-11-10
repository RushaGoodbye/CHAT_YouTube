"""Rearm stopped 885 review-only request from byte-verified backup; no worker.
Preserves incomplete render and signed scan caches, does not touch other jobs.
"""
import sys,json,uuid,os,time
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
BACKUP=DATA/"RG_REPAIR_BACKUPS"/"RG_FAST_V3_885_RESTART_20261110_132910_e8d53"
def atomic(path,obj):
    temp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)
def run():
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    from rg_fullstream_launcher_v2 import output_for_request
    base=DATA/"fullstream_v2"
    d=base/"885";req=d/"queue_request.json";status=d/"status.json"
    if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("ACTIVE_WORKER_REFUSED")
    if req.exists():raise RuntimeError("885_ALREADY_QUEUED_NO_DUPLICATE")
    st=json.loads(status.read_text(encoding="utf-8-sig"))
    if st.get("state")!="STOPPED_BY_USER":raise RuntimeError("885_NOT_STOPPED")
    raw=(BACKUP/"885_queue_before.json").read_bytes()
    job=json.loads(raw.decode("utf-8-sig"))
    if (job.get("stream")!="885" or job.get("repair") is not True
        or job.get("qa_preview_export_requested") is not True
        or job.get("qa_publication_allowed") is not False):
        raise RuntimeError("QA_ONLY_BACKUP_IDENTITY_NOT_CONFIRMED")
    output=output_for_request("885",job,APP)
    if output.exists():raise RuntimeError("FINAL_REVIEW_OUTPUT_EXISTS")
    queued=[]
    for n in range(886,890):
        q=base/str(n)/"queue_request.json"
        if not q.exists():raise RuntimeError("MISSING_"+str(n))
        row=json.loads(q.read_text(encoding="utf-8-sig"))
        if row.get("stream")!=str(n):raise RuntimeError("WRONG_"+str(n))
        queued.append((float(row["created_utc_epoch"]),str(n)))
    first=float(job["created_utc_epoch"])
    if not all(first<t for t,n in queued):raise RuntimeError("885_NOT_BEFORE_OTHERS")
    if "RG_FAST_POPUP_GBLUR_V1" not in (APP/"rg_fullstream_export_v1.py").read_text(encoding="utf-8-sig"):
        raise RuntimeError("FAST_RENDER_NOT_INSTALLED")
    newst=dict(state="QUEUED",stream="885",repair=True,
               qa_preview_export_requested=True,qa_only=True,editorial_approval=False,
               publish_ready=False,output=str(output),queued_at=first,
               qa_unresolved=["NOTIFICATION_COVERAGE_UNVERIFIED"])
    previous=status.read_bytes()
    try:
        if active_workers() or status.read_bytes()!=previous:raise RuntimeError("CONCURRENT_STARTED")
        with req.open("xb") as f:f.write(raw)
        atomic(status,newst)
        if json.loads(req.read_text(encoding="utf-8-sig"))!=job:raise RuntimeError("REQUEST_MISMATCH")
        if active_workers():raise RuntimeError("UNEXPECTED_WORKER")
        print("RGREARMFAST|RESTORED|885|QA_ONLY|TRUE",flush=True)
        print("RGREARMFAST|ORDER|885,886,887,888,889",flush=True)
        print("RGREARMFAST|OUTPUT|"+str(output),flush=True)
        print("RGREARMFAST|WORKER_STARTED|FALSE",flush=True)
        print("RGREARMFAST|ALL|PASS",flush=True)
    except BaseException:
        if not active_workers():
            req.unlink(missing_ok=True)
            status.write_bytes(previous)
            print("RGREARMFAST|ROLLBACK|RESTORED_STOP_STATUS",flush=True)
        raise
if __name__=="__main__":run()
