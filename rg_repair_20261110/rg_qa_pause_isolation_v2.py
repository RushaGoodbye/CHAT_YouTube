"""RG Full Stream QA pause isolation V1: transactional worker + engine-hash update.
No live worker shutdown, no queue mutation and no media changes.
"""
from pathlib import Path
import ast,hashlib,os,sys,time,uuid,argparse,json
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
WORKER="rg_fullstream_worker_v3.py"
UI="rg_fullstream_batch_v53.py"
ANCHOR_A="""            todo=request_files(data)
            if only_stream is not None:"""
REPLACE_A="""            todo=request_files(data)
            # RG_QA_PAUSE_ISOLATION_V1: in batch mode, don't retry a QA-paused
            # job automatically. Preserve its request for explicit selected review.
            if only_stream is None:
                eligible=[]
                for queued in todo:
                    sf=queued[1].parent/'status.json'
                    try:
                        state=json.loads(sf.read_text(encoding='utf-8-sig')).get('state')
                    except (OSError,ValueError,TypeError,AttributeError):
                        state=None
                    if state=='PAUSED_EDITORIAL_QA':
                        emit('EDITORIAL_QA_SKIPPED_IN_BATCH',stream=queued[2]['stream'],
                             queue_preserved=True)
                        continue
                    eligible.append(queued)
                todo=eligible
            if only_stream is not None:"""
ANCHOR_B="""                        return 4  # Do not continue risking hours of pointless encoding."""
REPLACE_B="""                        # RG_QA_PAUSE_ISOLATION_V1: keep the blocked request
                        # and proceed to OTHER streams, not another attempt on
                        # the same stream. No render, no QA override.
                        if only_stream is not None:
                            return 4
                        continue"""
def h(b):return hashlib.sha256(b).hexdigest()
def patch(raw,old,new):
    txt=raw.decode("utf-8-sig").replace("\r\n","\n")
    if txt.count(old)!=1:raise RuntimeError("ANCHOR_NOT_UNIQUE:"+old[:35])
    result=txt.replace(old,new,1)
    ast.parse(result)
    return result.replace("\n","\r\n").encode("utf-8") if b"\r\n" in raw else result.encode("utf-8")
def log(*v):print("RGQAPAUSE|"+"|".join(map(str,v)),flush=True)
def prepare():
    originals={n:(APP/n).read_bytes() for n in [WORKER,UI]}
    w=patch(originals[WORKER],ANCHOR_A,REPLACE_A)
    w=patch(w,ANCHOR_B,REPLACE_B)
    oldsha=h(originals[WORKER]);newsha=h(w)
    uitext=originals[UI].decode("utf-8-sig")
    if uitext.count(oldsha)!=1:raise RuntimeError("UI_SHA_EXPECTATION_MISMATCH")
    ui=uitext.replace(oldsha,newsha,1).encode("utf-8")
    ast.parse(ui.decode())
    return originals,{WORKER:w,UI:ui}
def install():
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_FULLSTREAM_WORKER_INSTALL_ABORT")
    originals,modified=prepare()
    log("STATIC_COMPILE","PASS")
    log("WORKER_BEFORE",h(originals[WORKER]),"AFTER",h(modified[WORKER]))
    log("UI_BEFORE",h(originals[UI]),"AFTER",h(modified[UI]))
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_QA_PAUSE_ISOLATION_V1_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True,exist_ok=False)
    for n,b in originals.items():
        p=backup/n
        p.write_bytes(b)
        if p.read_bytes()!=b:raise RuntimeError("BACKUP_UNVERIFIED:"+n)
    done=[]
    try:
        if active_workers():raise RuntimeError("NEW_WORKER_RACE_ABORT")
        for n in [WORKER,UI]:
            p=APP/n
            if p.read_bytes()!=originals[n]:raise RuntimeError("CONCURRENT_CHANGE_"+n)
            temp=p.with_name(p.name+".rg_qapause.tmp")
            temp.write_bytes(modified[n])
            if temp.read_bytes()!=modified[n]:raise RuntimeError("STAGED_BAD:"+n)
            os.replace(temp,p)
            done.append(n)
        for n,b in modified.items():
            if (APP/n).read_bytes()!=b:raise RuntimeError("VERIFY_FAILED_"+n)
        log("INSTALL","PASS","BACKUP",backup)
    except BaseException:
        for n in done[::-1]:
            (APP/n).write_bytes(originals[n])
        log("ROLLBACK","ATTEMPTED",backup)
        raise
def test():
    originals,modified=prepare()
    s=modified[WORKER].decode("utf-8").replace("\r\n","\n")
    assert "EDITORIAL_QA_SKIPPED_IN_BATCH" in s
    assert "if only_stream is not None:\n                            return 4" in s
    assert "                        continue" in s
    assert h(modified[WORKER]) in modified[UI].decode()
    # This static validation does not run a worker, render, or alter state.
    log("TEST","PASS","NO_MEDIA_NO_WORKER")
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--install",action="store_true");v=a.parse_args()
    install() if v.install else test()
