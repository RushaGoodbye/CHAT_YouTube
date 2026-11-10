"""Unblock 895 manual Studio retry after a QA pause.
Move ONLY the stale queue_request.json to a named backup directory.
Keep all status, masks, ASR checkpoints, finished MP4 and source unchanged.
No background worker spawn and no rendering.
"""
from pathlib import Path
import json,sys,os,uuid,time,hashlib
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=DATA/"fullstream_v2"/"895"
def hashfile(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    p=ROOT/"queue_request.json"
    statuspath=ROOT/"status.json"
    configpath=ROOT/"plan.json"
    asrpath=ROOT/"recognized_words.json"
    existingpath=ROOT/"processing_plan.json"
    if not p.is_file():raise RuntimeError("NO_STALE_QUEUE_FILE")
    s=json.loads(statuspath.read_text(encoding="utf-8-sig"))
    q=json.loads(p.read_text(encoding="utf-8-sig"))
    manual=json.loads(configpath.read_text(encoding="utf-8-sig"))
    if s.get("state")!="PAUSED_EDITORIAL_QA":raise RuntimeError("NOT_QA_PAUSED")
    if s.get("blocking_reasons")!=["NOTIFICATION_COVERAGE_UNVERIFIED"]:raise RuntimeError("UNEXPECTED_QA_REASONS")
    if str(q.get("stream"))!="895" or q.get("schema")!="RG_FULLSTREAM_QUEUE_V3":
        raise RuntimeError("NOT_ORIGINAL_STALE_REQUEST")
    if not (len(manual.get("popup_masks",[]))==1 and asrpath.is_file() and existingpath.is_file()):
        raise RuntimeError("QA_INPUTS_CHANGED")
    if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("ACTIVE_WORKER_ABORT")
    protected={path:hashfile(path) for path in (statuspath,configpath,asrpath,existingpath)}
    folder=DATA/"RG_REPAIR_BACKUPS"/("RG895_PAUSED_QUEUE_REQUEST_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True,exist_ok=False)
    destination=folder/"queue_request_895_paused_before.json"
    original=p.read_bytes()
    (folder/"README.txt").write_text("Saved pre-existing QA-paused RG895 queue request to permit one manual Studio recheck. No worker automatically started. Original request restored by moving this file to fullstream_v2/895/queue_request.json ONLY when idle.\n",encoding="utf-8")
    try:
        if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("WORKER_STARTED_ABORT")
        os.replace(p,destination)
        if destination.read_bytes()!=original:raise RuntimeError("ARCHIVE_MISMATCH")
        if any(hashfile(path)!=original_hash for path,original_hash in protected.items()):
            raise RuntimeError("PROTECTED_QA_FILE_CHANGED")
        if p.exists():raise RuntimeError("QUEUE_REQUEST_REMAINS")
        if worker_lock_state(DATA)!="IDLE":raise RuntimeError("UNEXPECTED_WORKER_STARTED")
    except:
        if not p.exists() and destination.exists():os.replace(destination,p)
        print("RG895UNBLOCK|ROLLED_BACK",flush=True)
        raise
    print("RG895UNBLOCK|STALE_QUEUE_REQUEST_ARCHIVED|PASS",flush=True)
    print("RG895UNBLOCK|BACKUP|"+str(destination),flush=True)
    print("RG895UNBLOCK|ASR_CHECKPOINT_UNCHANGED|PASS",flush=True)
    print("RG895UNBLOCK|MANUAL_BARS_MASK_UNCHANGED|PASS",flush=True)
    print("RG895UNBLOCK|QA_STILL_BLOCKED|"+s["state"],flush=True)
    print("RG895UNBLOCK|READY_FOR_USER_STUDIO_RECHECK_BUTTON|PASS",flush=True)
if __name__=="__main__":main()
