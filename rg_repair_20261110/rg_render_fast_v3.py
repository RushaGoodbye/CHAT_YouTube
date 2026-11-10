"""RG Render Fast V3: timeline-gated popup Gaussian, one-frame underlay mask,
and FFmpeg filter graph thread budget of 8 (AlexPC i9-12900 benchmark).
Fail-closed transactional installer; only when no fullstream worker is alive.
"""
from pathlib import Path
import os,sys,time,uuid,ast,argparse
from rg_render_fast_v2 import patch as v2_patch
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
FILE=APP/"rg_fullstream_export_v1.py"
OLD="cmd+=['-filter_complex_script',str(filterfile),'-map','[vout]','-map','[aout]',"
NEW="cmd+=['-filter_complex_threads','8','-filter_complex_script',str(filterfile),'-map','[vout]','-map','[aout]',"
def patch(raw):
    f=v2_patch(raw)
    s=f.decode("utf-8-sig").replace("\r\n","\n")
    if s.count(OLD)!=1:raise RuntimeError("FFMPEG_OPTIONS_ANCHOR_NOT_UNIQUE")
    s=s.replace(OLD,NEW)
    ast.parse(s)
    return s.replace("\n","\r\n").encode("utf-8") if b"\r\n" in raw else s.encode("utf-8")
def run(install=False):
    before=FILE.read_bytes();after=patch(before)
    print("RGRENDERFAST|STATIC|PASS|THREE_OPTIMIZATIONS",flush=True)
    if not install:return
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_RG_FULLSTREAM_WORKER_NO_INSTALL")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_RENDER_FAST_V3_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True,exist_ok=False)
    (backup/FILE.name).write_bytes(before)
    if (backup/FILE.name).read_bytes()!=before:raise RuntimeError("BACKUP_NOT_VERIFIED")
    staging=FILE.with_name(FILE.name+".rgfast_v3.tmp")
    try:
        if active_workers() or FILE.read_bytes()!=before:raise RuntimeError("WORKER_OR_CONCURRENT_FILE_CHANGE")
        staging.write_bytes(after)
        if staging.read_bytes()!=after:raise RuntimeError("STAGING_VERIFICATION_FAILED")
        os.replace(staging,FILE)
        if FILE.read_bytes()!=after:raise RuntimeError("FINAL_VERIFICATION_FAILED")
        print("RGRENDERFAST|INSTALL|PASS|BACKUP|"+str(backup),flush=True)
    except BaseException:
        FILE.write_bytes(before)
        print("RGRENDERFAST|ROLLBACK|ATTEMPTED",flush=True)
        raise
    finally:staging.unlink(missing_ok=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--install",action="store_true")
    a=p.parse_args()
    run(a.install)
