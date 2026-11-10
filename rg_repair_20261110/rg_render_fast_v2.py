"""V2: add single-frame mask computation to exact popup gated gblur.
This script never touches installed code unless --install and all workers idle.
"""
import ast,sys,os,uuid,time,argparse
from pathlib import Path
from rg_fast_popup_gblur_v1 import patched as popup_patch
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
FILE=APP/"rg_fullstream_export_v1.py"
OLD="lines.append('[rg_maskseed]format=yuv420p,lutyuv=y=0:u=0:v=0,'"
NEW="""# RG_ONE_FRAME_MASK_V1: image mask uses constant geometry, not source pixels.
        # Compute the exact existing YUV mask from first frame only.
        # maskedmerge frame sync repeats its most recent mask frame.
        lines.append('[rg_maskseed]trim=end_frame=1,format=yuv420p,lutyuv=y=0:u=0:v=0,'"""
def patch(raw):
    first=popup_patch(raw)
    txt=first.decode("utf-8-sig").replace("\r\n","\n")
    if txt.count(OLD)!=1:raise RuntimeError("STATIC_MASK_ANCHOR_NOT_UNIQUE")
    txt=txt.replace(OLD,NEW)
    ast.parse(txt)
    return txt.replace("\n","\r\n").encode("utf-8") if b"\r\n" in raw else txt.encode("utf-8")
def main(install):
    before=FILE.read_bytes();after=patch(before)
    print("RGFASTV2|SOURCE|PASS",flush=True)
    if not install:return
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("ACTIVE_RENDER_INSTALL_DENIED")
    back=DATA/"RG_REPAIR_BACKUPS"/("RG_RENDER_FAST_V2_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    back.mkdir(parents=True)
    (back/FILE.name).write_bytes(before)
    if (back/FILE.name).read_bytes()!=before:raise RuntimeError("BAD_BACKUP")
    tmp=FILE.with_name(FILE.name+".rgfastv2.tmp")
    try:
        if FILE.read_bytes()!=before:raise RuntimeError("CONCURRENT_CHANGED")
        tmp.write_bytes(after)
        if tmp.read_bytes()!=after:raise RuntimeError("TEMP_FAILED")
        os.replace(tmp,FILE)
        if FILE.read_bytes()!=after:raise RuntimeError("POST_VERIFY")
        print("RGFASTV2|INSTALLED|PASS|BACKUP|"+str(back),flush=True)
    except:
        FILE.write_bytes(before)
        print("RGFASTV2|ROLLBACK|ATTEMPTED",flush=True)
        raise
    finally:tmp.unlink(missing_ok=True)
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--install",action="store_true")
    main(a.parse_args().install)
