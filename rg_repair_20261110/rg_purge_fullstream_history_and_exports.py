"""RG Full Stream complete history and rendered output cleanup.
Explicitly user-requested permanent deletion. Narrowly scoped to:
 - DATA/fullstream_v2/<numeric stream id> history, QA/cache/queue
 - APP/<numeric stream id>/FULLSTREAM_YOUTUBE/ export folders
 - worker history log(s) in DATA/fullstream_v2 root.
Never touch input source video/audio (NAS), dialogue outputs, Studio app, model/runtime,
backups, or source-independent app folders. Never delete while rendering.
"""
from pathlib import Path
import sys, shutil, re, os, time, json
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
HISTORY=DATA/"fullstream_v2"
NUM=re.compile(r"^[0-9]{3,5}$")
def ensure_safe(path,root):
    path=Path(path)
    if path.is_symlink() or path.is_junction():raise RuntimeError("REPARSE_POINT_REFUSED:"+str(path))
    if path.parent.resolve(strict=True)!=root.resolve(strict=True):raise RuntimeError("PATH_OUTSIDE_APPROVED_ROOT:"+str(path))
    if root.is_symlink() or root.is_junction():raise RuntimeError("ROOT_REPARSE_REFUSED")
def sum_bytes(dir):
    total=0
    for p in dir.rglob("*"):
        if p.is_symlink() or p.is_junction():raise RuntimeError("NESTED_REPARSE_POINT_REFUSED:"+str(p))
        if p.is_file():total+=p.stat().st_size
    return total
def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--delete",action="store_true")
    args=parser.parse_args()
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    import subprocess
    if not APP.is_dir() or not HISTORY.is_dir():raise RuntimeError("ROOT_MISSING")
    # Protect video rendering in progress and other active workers
    if active_workers():
        raise RuntimeError("ACTIVE_RG_WORKERS_NO_DELETE:"+repr([(x.get("ProcessId"),str(x.get("CommandLine"))[:100]) for x in active_workers()]))
    lock=worker_lock_state(DATA)
    print("RGCLEAN|LOCK|"+str(lock),flush=True)
    if lock!="IDLE":raise RuntimeError("FULLSTREAM_LOCK_NOT_IDLE:"+str(lock))
    # Secondary external process guard; with no worker there should be no ffmpeg render
    ps=subprocess.run(["powershell","-NoProfile","-Command",
         r"Get-CimInstance Win32_Process | Where-Object {$_.Name -match 'ffmpeg|python' -and $_.CommandLine -match 'RG_\d+_FULL_YOUTUBE.*rendering\.mp4|rg_fullstream_worker_v3\.py|rg_fullstream_auto_v2\.py'} | Select-Object -ExpandProperty ProcessId"],
         capture_output=True,text=True,timeout=20)
    if ps.returncode!=0:raise RuntimeError("PROCESS_GUARD_FAILED:"+ps.stderr[-200:])
    if ps.stdout.strip():raise RuntimeError("ACTIVE_VIDEO_PROCESS_FOUND:"+ps.stdout.strip())
    hist=[]
    for p in HISTORY.iterdir():
        if p.is_dir() and NUM.fullmatch(p.name):
            ensure_safe(p,HISTORY);hist.append(p)
        elif p.is_symlink():raise RuntimeError("UNSAFE_LINK_IN_HISTORY")
    exports=[]
    for p in APP.iterdir():
        if p.is_dir() and NUM.fullmatch(p.name):
            export=p/"FULLSTREAM_YOUTUBE"
            if export.exists():
                ensure_safe(export,p)
                exports.append(export)
    lognames=("queue_worker.log","queue_worker.err.log","queue_worker.stdout.log","queue_worker.stderr.log")
    logs=[HISTORY/n for n in lognames if (HISTORY/n).is_file()]
    for p in logs:ensure_safe(p,HISTORY)
    print("RGCLEAN|HISTORY_DIRS|"+str(len(hist)),flush=True)
    print("RGCLEAN|EXPORT_DIRS|"+str(len(exports)),flush=True)
    print("RGCLEAN|LOGS|"+json.dumps([p.name for p in logs]),flush=True)
    countfiles=0;countbytes=0
    for name, group in (("HISTORY",hist),("EXPORT",exports)):
        for d in group:
            sz=sum_bytes(d)
            countbytes+=sz
            print("RGCLEAN|TARGET|"+name+"|"+str(d)+"|"+str(sz),flush=True)
    countbytes+=sum(p.stat().st_size for p in logs)
    print("RGCLEAN|TOTAL_BYTES|"+str(countbytes),flush=True)
    if len(hist)<1:raise RuntimeError("NO_HISTORY_DIRS_UNEXPECTED")
    if not args.delete:
        print("RGCLEAN|DRY_RUN|PASS",flush=True)
        return
    # Prevent easy race with existing fullstream workers by checking immediately
    if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("WORKER_STARTED_ABORT")
    # Destructive user-authorized paths only. Never traverse reparse points.
    deleted=0;failed=[]
    for name,group in (("EXPORT",exports),("HISTORY",hist)):
        for d in group:
            try:
                ensure_safe(d, d.parent)
                shutil.rmtree(d)
                if d.exists():raise RuntimeError("DIRECTORY_REMAINS")
                print("RGCLEAN|DELETED|"+name+"|"+d.name+"|"+str(d),flush=True)
                deleted+=1
            except Exception as exc:
                failed.append((str(d),type(exc).__name__,str(exc)))
                print("RGCLEAN|ERROR|"+str(d)+"|"+repr(exc),flush=True)
    for p in logs:
        try:
            p.unlink()
            print("RGCLEAN|DELETED_LOG|"+p.name,flush=True)
        except Exception as exc:
            failed.append((str(p),str(exc)))
    # Status proof
    remaining_h=[p.name for p in HISTORY.iterdir() if p.is_dir() and NUM.fullmatch(p.name)]
    remaining_e=[str(p) for p in exports if p.exists()]
    print("RGCLEAN|SUMMARY|DELETED="+str(deleted)+"|BYTES_PLANNED="+str(countbytes)+
          "|REMAINING_HISTORY="+str(remaining_h)+"|REMAINING_EXPORTS="+str(remaining_e)+
          "|ERRORS="+str(failed),flush=True)
    if failed or remaining_h or remaining_e:raise RuntimeError("PARTIAL_CLEANUP_REVIEW_REQUIRED")
    print("RGCLEAN|COMPLETE|PASS|SOURCE_AND_DIALOGUE_UNTOUCHED",flush=True)
if __name__=="__main__":main()
