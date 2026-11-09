"""One-shot transactional quarantine for FULL STREAM derivatives of 885..899.
Never modifies inputs, dialogue exports, program files or starts any worker.
"""
import json,os,sys,time,uuid
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
BASE=DATA/"fullstream_v2"
IDS=[str(i) for i in range(885,900)]
QA_ROOT=DATA/"FULLSTREAM_FRESH_START_QUARANTINE"
def log(*a):print("RGFRESHRESET|"+"|".join(str(x) for x in a),flush=True)

def worker_idle():
    sys.path.insert(0,str(APP))
    from rg_fullstream_process_state_v59 import worker_lock_state
    from rg_fullstream_stop_v60 import active_workers
    lock=worker_lock_state(DATA)
    running=active_workers()
    log("WORKER_LOCK",lock,"PIDS",",".join(str(r["ProcessId"]) for r in running))
    if lock!="IDLE" or running:raise RuntimeError("ACTIVE_WORKER_RESET_FORBIDDEN")

def main():
    worker_idle()
    if not APP.is_dir() or not BASE.is_dir():raise RuntimeError("EXPECTED_ROOT_NOT_FOUND")
    targets=[]
    for s in IDS:
        for kind,src in [("data",BASE/s),("output",APP/s/"FULLSTREAM_YOUTUBE")]:
            if not src.exists():continue
            if not src.is_dir() or src.is_symlink() or src.is_junction():
                raise RuntimeError("UNSAFE_FOLDER:"+str(src))
            allowed_parent=(BASE if kind=="data" else APP/s)
            if src.parent.resolve()!=allowed_parent.resolve():
                raise RuntimeError("PATH_OUTSIDE_EXPECTED_PARENT:"+str(src))
            targets.append((s,kind,src))
    log("TARGETS",len(targets),"STREAMS",",".join(IDS))
    root=QA_ROOT/("885_899_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    if root.exists():raise RuntimeError("ARCHIVE_COLLISION")
    root.mkdir(parents=True)
    ledger={"schema":"RG_FULLSTREAM_FRESH_885_899_V1","streams":IDS,
            "source_media_untouched":True,"dialogue_files_untouched":True,
            "worker_started":False,"entries":[],"status":"PREPARED"}
    journal=root/"manifest.json"
    def save():
        tmp=journal.with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(tmp,journal)
    save()
    moved=[]
    try:
        worker_idle()
        for s,kind,src in targets:
            dest=root/kind/s
            dest.parent.mkdir(parents=True,exist_ok=True)
            if not src.exists() or dest.exists():raise RuntimeError("RACE_OR_DEST_EXISTS:"+str(src))
            os.rename(src,dest)
            moved.append((src,dest))
            ledger["entries"].append({"stream":s,"kind":kind,"original":str(src),"quarantine":str(dest)})
            save()
            log("QUARANTINED",s,kind)
        for s,kind,src in targets:
            if src.exists():raise RuntimeError("PRODUCTION_PATH_NOT_EMPTY:"+str(src))
        ledger["status"]="QUARANTINED_VERIFIED"
        save()
    except Exception:
        log("ROLLBACK","START")
        for src,dst in reversed(moved):
            if dst.exists() and not src.exists():os.rename(dst,src)
            else:log("ROLLBACK_MANUAL_CHECK",src,dst)
        ledger["status"]="ROLLED_BACK_CHECK"
        save()
        raise
    log("PASS","FRESH_WORKING_PATHS_EMPTY","ARCHIVE",root)
    log("NO_JOB_LAUNCHED","TRUE")
if __name__=="__main__":main()
