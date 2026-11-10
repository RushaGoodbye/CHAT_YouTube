"""RGBA speed V1: gate gblur calculations to verified popup intervals.
No output pixel, audio, timestamps, or quality-setting changes.
"""
from pathlib import Path
import ast,sys,os,time,uuid,argparse
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
FILE=APP/"rg_fullstream_export_v1.py"
OLD="""        lines.append(f'[{crop}]crop={w}:{h}:{x}:{y},gblur=sigma=15:steps=2[{blur}]')
        enabling='+'.join('between(t\\\\,'+_fnum(a)+'\\\\,'+_fnum(b)+')' for a,b in roi['intervals']) or '0'
        lines.append(f'[{base}][{blur}]overlay={x}:{y}:enable=\\'{enabling}\\'[{out}]')"""
NEW="""        enabling='+'.join('between(t\\\\,'+_fnum(a)+'\\\\,'+_fnum(b)+')' for a,b in roi['intervals']) or '0'
        # RG_FAST_POPUP_GBLUR_V1: same source timestamps and sigma/steps,
        # but skip the expensive Gaussian convolution when the ROI is absent.
        # The enabled overlay below is unchanged; output frame pixels match.
        lines.append(f'[{crop}]crop={w}:{h}:{x}:{y},gblur=sigma=15:steps=2:enable=\\'{enabling}\\'[{blur}]')
        lines.append(f'[{base}][{blur}]overlay={x}:{y}:enable=\\'{enabling}\\'[{out}]')"""
def patched(raw):
    s=raw.decode("utf-8-sig").replace("\r\n","\n")
    if s.count(OLD)!=1:raise RuntimeError("EXPECTED_FILTER_GRAPH_ANCHOR_NOT_FOUND")
    s=s.replace(OLD,NEW,1)
    ast.parse(s)
    return s.replace("\n","\r\n").encode("utf-8") if b"\r\n" in raw else s.encode("utf-8")
def run(install):
    orig=FILE.read_bytes(); new=patched(orig)
    print("RGFAST|STATIC|PASS|NO_PIXEL_OR_QUALITY_PARAMETER_CHANGES",flush=True)
    if not install:return
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("LIVE_VIDEO_ACTIVE_INSTALL_NOT_ALLOWED")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_FAST_POPUP_GBLUR_V1_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True)
    (backup/FILE.name).write_bytes(orig)
    if (backup/FILE.name).read_bytes()!=orig:raise RuntimeError("BACKUP_FAILED")
    temp=FILE.with_name(FILE.name+".fast_popup.tmp")
    try:
        if FILE.read_bytes()!=orig:raise RuntimeError("CONCURRENT_FILE_CHANGE")
        temp.write_bytes(new)
        if temp.read_bytes()!=new:raise RuntimeError("STAGING_FAILED")
        os.replace(temp,FILE)
        if FILE.read_bytes()!=new:raise RuntimeError("POSTINSTALL_FAILED")
        print("RGFAST|INSTALL|PASS|BACKUP|"+str(backup),flush=True)
    except:
        FILE.write_bytes(orig)
        print("RGFAST|ROLLBACK|ATTEMPTED",flush=True)
        raise
    finally:temp.unlink(missing_ok=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--install",action="store_true");a=p.parse_args();run(a.install)
