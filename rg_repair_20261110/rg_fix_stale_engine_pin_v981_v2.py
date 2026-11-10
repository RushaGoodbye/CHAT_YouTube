"""V9.8.1 repair two stale engine guard SHA256 pins with exact known hashes.

The actual export code was previously approved as FAST V3 sha:
82d85e81c68534cd591bb43344e906533593ecbb3722369cb455c83e9fd42bad.
The QA-only export currently deployed has sha:
7882cd27e4b4f0915faa42430843bfe41193c466583a77ffee96bb3f02ca25e1.
All other 24 expected pins must match. Worker must be idle. Backup & rollback.
No video or queue edits.
"""
from pathlib import Path
import ast,sys,hashlib,uuid,os,time,inspect
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
BATCH=APP/"rg_fullstream_batch_v53.py"
OLD={
"rg_fullstream_export_v1.py":("8bb18dc9b2e6d83b4cd2972d2e14fc2ec9fb04f38373d43ea846f6316921b68b",
"82d85e81c68534cd591bb43344e906533593ecbb3722369cb455c83e9fd42bad"),
"rg_fullstream_qa_export_v96.py":("98ce13994c4909034ba41955a65c2cd1682b76bf360d1ace243b85ff3cd7212e",
"7882cd27e4b4f0915faa42430843bfe41193c466583a77ffee96bb3f02ca25e1")}
EXPECTED_BATCH="c53509b671cbfa468cc8e81747240db9c68b14fe7aa9e3ac7ec808c8b41a9c01"
def sha(b):return hashlib.sha256(b).hexdigest()
def prepare():
    before=BATCH.read_bytes()
    if sha(before)!=EXPECTED_BATCH:raise RuntimeError("BATCH_CHANGED_CONCURRENTLY")
    text=before.decode("utf-8-sig")
    for name,(old,new) in OLD.items():
        if sha((APP/name).read_bytes())!=new:raise RuntimeError("PRODUCTION_TARGET_HASH_UNEXPECTED_"+name)
        if text.count(old)!=1:raise RuntimeError("EXPECTED_PIN_MISSING_OR_DUPLICATED_"+name)
        text=text.replace(old,new,1)
    ast.parse(text)
    out=text.encode("utf-8")
    if before.startswith(b"\xef\xbb\xbf"):out=b"\xef\xbb\xbf"+out
    if b"\r\n" in before:out=out.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n")
    if len(out)!=len(before):raise RuntimeError("SAME_SIZE_PIN_REPLACEMENT_FAILED")
    return before,out
def test(updated):
    import types
    sys.path.insert(0,str(APP))
    ns={"APP":APP,"Path":Path,"hashlib":hashlib}
    tree=ast.parse(updated.decode("utf-8-sig"))
    f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="engine_v710_verified")
    exec(compile(ast.fix_missing_locations(ast.Module(body=[f],type_ignores=[])),"<V981-engine>","exec"),ns)
    if ns["engine_v710_verified"](APP) is not True:
        raise RuntimeError("ENGINE_HASH_GUARD_STILL_REFUSES_AFTER_PIN_FIX")
    print("RGV981|ALL_26_ENGINE_HASH_PINS|PASS",flush=True)
def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--install",action="store_true")
    args=p.parse_args()
    before,after=prepare()
    test(after)
    if not args.install:
        print("RGV981|DRYRUN|PASS",flush=True);return
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_WORKER_SAFE_STOP")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_V981_FIX_ENGINE_HASH_GUARD_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True,exist_ok=False)
    (backup/BATCH.name).write_bytes(before)
    if (backup/BATCH.name).read_bytes()!=before:raise RuntimeError("BACKUP_VERIFICATION_FAILED")
    try:
        if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("WORKER_STARTED_ABORT")
        if BATCH.read_bytes()!=before:raise RuntimeError("BATCH_CHANGED_BEFORE_WRITE")
        tmp=BATCH.with_name(BATCH.name+"."+uuid.uuid4().hex+".tmp")
        try:
            tmp.write_bytes(after)
            if sha(tmp.read_bytes())!=sha(after):raise RuntimeError("STAGING_HASH_FAIL")
            os.replace(tmp,BATCH)
        finally:tmp.unlink(missing_ok=True)
        if BATCH.read_bytes()!=after:raise RuntimeError("POST_INSTALL_BYTES_MISMATCH")
        # Post-install actual runtime import and guard.
        import importlib
        sys.path.insert(0,str(APP))
        import rg_fullstream_batch_v53 as batch
        if not batch.engine_v710_verified(APP):raise RuntimeError("PRODUCTION_ENGINE_GUARD_FALSE")
        print("RGV981|INSTALLED|PASS|"+str(backup),flush=True)
        print("RGV981|NO_QUEUES_OR_VIDEO_TOUCHED|PASS",flush=True)
    except:
        BATCH.write_bytes(before)
        print("RGV981|ROLLBACK|DONE",flush=True)
        raise
if __name__=="__main__":main()
