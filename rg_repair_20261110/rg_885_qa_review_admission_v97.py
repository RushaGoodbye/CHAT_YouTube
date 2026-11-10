"""RG 885 QA review-only V97:
Allow explicitly requested QA-only render when bilingual profanity V90 is
skipped by policy; do not approve privacy verification or permit publication.
"""
import ast,hashlib,os,sys,time,uuid,argparse,json
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
NAME="rg_fullstream_qa_export_v96.py"
OLD='''    if (not isinstance(v90,dict) or not v90.get("complete")
        or not isinstance(v87,dict) or not v87.get("complete")
        or int(v87.get("unexamined") or 0)>0):
        result["reason"]="SOURCE_AUDIO_REVIEW_INCOMPLETE"
        return result'''
NEW='''    # RG_QA_PREVIEW_V97: user disabled profanity censorship. No V90 RU+UK
    # recheck is needed for an explicitly requested QA-only review export.
    # V87 acoustic QA remains mandatory; unverified video popups stay blocked
    # from publication in the resulting MP4/sidecar.
    v90_skipped_by_policy=(isinstance(v90,dict) and
        v90.get("schema")=="RG_V90_SKIPPED_NO_PROFANITY_CENSORSHIP" and
        v90.get("skipped_reason")=="MAT_CENSORSHIP_DISABLED")
    v90_review_completed=(isinstance(v90,dict) and v90.get("complete") is True)
    if (not (v90_skipped_by_policy or v90_review_completed)
        or not isinstance(v87,dict) or not v87.get("complete")
        or int(v87.get("unexamined") or 0)>0):
        result["reason"]="SOURCE_AUDIO_REVIEW_INCOMPLETE"
        return result'''
def build(raw):
    text=raw.decode("utf-8-sig").replace("\r\n","\n")
    if text.count(OLD)!=1:raise RuntimeError("SOURCE_ANCHOR_NOT_UNIQUE")
    text=text.replace(OLD,NEW,1)
    ast.parse(text)
    return text.replace("\n","\r\n").encode("utf-8") if b"\r\n" in raw else text.encode("utf-8")
def main(do_install):
    dst=APP/NAME;original=dst.read_bytes();modified=build(original)
    print("RGQA97|STATIC|PASS",flush=True)
    if not do_install:return
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("ACTIVE_WORKER_INSTALL_ABORT")
    root=DATA/"RG_REPAIR_BACKUPS"/("RG_QA_PREVIEW_V97_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    root.mkdir(parents=True)
    saved=root/NAME;saved.write_bytes(original)
    if saved.read_bytes()!=original:raise RuntimeError("BACKUP_VERIFICATION_FAILED")
    try:
        if dst.read_bytes()!=original:raise RuntimeError("FILE_CHANGED_BEFORE_INSTALL")
        temp=dst.with_suffix(".review97.tmp");temp.write_bytes(modified)
        if temp.read_bytes()!=modified:raise RuntimeError("PATCH_STAGING_FAILED")
        os.replace(temp,dst)
        if dst.read_bytes()!=modified:raise RuntimeError("POST_VERIFY_FAILED")
        print("RGQA97|INSTALLED|PASS|BACKUP="+str(root),flush=True)
    except:
        dst.write_bytes(original)
        print("RGQA97|ROLLED_BACK",flush=True)
        raise
    finally:
        temp.unlink(missing_ok=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--install",action="store_true")
    main(p.parse_args().install)
