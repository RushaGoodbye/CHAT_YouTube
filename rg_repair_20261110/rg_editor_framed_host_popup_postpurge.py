"""RG manual framed host notification support V1, editor-confirmed only.
Update auto_v2 and batch engine hash atomically on idle worker; preserve old files.
"""
import ast,hashlib,os,sys,time,uuid,argparse
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
AUTO="rg_fullstream_auto_v2.py"
BATCH="rg_fullstream_batch_v53.py"
OLD="""            solo=(item.get('layout')=='solo' and item.get('layout_verified') is True)
            area=popup_search_area('solo' if solo else 'dual')"""
NEW="""            # RG_EDITOR_FRAMED_HOST_POPUP_V1: only accept this wider host pane
            # with an explicit editor confirmation. Never weaken the automatic
            # visual detector for unknown layouts or candidate images.
            layout=str(item.get('layout') or 'dual')
            if layout=='framed_host':
                if (item.get('layout_verified') is not True or
                        item.get('editor_confirmed') is not True):
                    flags.append('EDITOR_FRAMED_HOST_NOT_CONFIRMED')
                    continue
                area=popup_search_area('framed_host')
            else:
                solo=(layout=='solo' and item.get('layout_verified') is True)
                area=popup_search_area('solo' if solo else 'dual')"""
def sha(b):return hashlib.sha256(b).hexdigest()
def build():
    original={n:(APP/n).read_bytes() for n in (AUTO,BATCH)}
    raw=original[AUTO]
    s=raw.decode("utf-8-sig").replace("\r\n","\n")
    if s.count(OLD)!=1:raise RuntimeError("VERIFIED_POPUP_MANUAL_ANCHOR_NOT_UNIQUE")
    s=s.replace(OLD,NEW,1)
    ast.parse(s)
    newauto=s.replace("\n","\r\n").encode("utf-8") if b"\r\n" in raw else s.encode("utf-8")
    b=original[BATCH]
    tx=b.decode("utf-8-sig")
    oldsha=sha(raw);newsha=sha(newauto)
    if tx.count(oldsha)!=1:raise RuntimeError("ENGINE_HASH_REFERENCES_NOT_EXACT")
    tx=tx.replace(oldsha,newsha,1)
    ast.parse(tx)
    newbatch=tx.encode("utf-8-sig") if b.startswith(b"\xef\xbb\xbf") else tx.encode("utf-8")
    return original,{AUTO:newauto,BATCH:newbatch}
def tests():
    before,after=build()
    source=after[AUTO].decode("utf-8-sig")
    ns={}
    import re
    from importlib.util import spec_from_file_location
    sys.path.insert(0,str(APP))
    # Read only the function AST and compile in isolation to verify logic.
    tree=ast.parse(source)
    f=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=="verified_popups")
    exec(compile(ast.fix_missing_locations(ast.Module(body=[f],type_ignores=[])),"verified_popups_test","exec"),ns)
    from rg_fullstream_detectors_v2 import popup_search_area
    assert popup_search_area("framed_host")[0]>0
    # Post-purge synthetic editor evidence. Historical per-stream QA data was
    # intentionally deleted by the user and MUST NOT be recreated.
    framed=dict(x=1026,y=670,width=304,height=83,layout="framed_host",
                intervals=[[385.8,388.2]],editor_confirmed=True,layout_verified=True)
    dual=dict(x=557,y=498,width=370,height=130,layout="dual",
              intervals=[[4500.8,4514.7]],editor_confirmed=True,layout_verified=True)
    masks,flags=ns["verified_popups"]({"popup_masks":[framed,dual]})
    if len(masks)!=2 or flags:raise RuntimeError("SYNTHETIC_MASKS_REJECTED:"+repr(flags))
    for field in ("editor_confirmed","layout_verified"):
        invalid=dict(framed);invalid[field]=False
        bad,_=ns["verified_popups"]({"popup_masks":[invalid]})
        if bad:raise RuntimeError("UNVERIFIED_FRAMED_HOST_ACCEPTED")
    print("RGFRAMED|STATIC|PASS|DUAL_FRAMED_HOST|NEGATIVE_CONTROLS",flush=True)
    return before,after
def install():
    originals,new=tests()
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("RG_FULLSTREAM_ACTIVE_DEFER_INSTALL")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_EDITOR_FRAMED_HOST_V1_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True,exist_ok=False)
    for n,b in originals.items():
        (backup/n).write_bytes(b)
        if (backup/n).read_bytes()!=b:raise RuntimeError("BACKUP_SHA_MISMATCH_"+n)
    done=[]
    try:
        if active_workers():raise RuntimeError("WORKER_STARTED_INSTALL_ABORT")
        for n in (AUTO,BATCH):
            p=APP/n
            if p.read_bytes()!=originals[n]:raise RuntimeError("CODE_CHANGED_CONCURRENTLY_"+n)
            temp=p.with_suffix(".rgframed.tmp")
            temp.write_bytes(new[n])
            if temp.read_bytes()!=new[n]:raise RuntimeError("TEMP_WRITE_FAILED_"+n)
            os.replace(temp,p)
            done.append(n)
        if any((APP/n).read_bytes()!=new[n] for n in (AUTO,BATCH)):raise RuntimeError("POST_VERIFY_FAILED")
        print("RGFRAMED|INSTALL|PASS|BACKUP|"+str(backup),flush=True)
    except BaseException:
        for n in reversed(done):(APP/n).write_bytes(originals[n])
        print("RGFRAMED|ROLLBACK|ATTEMPTED",flush=True)
        raise
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--install",action="store_true")
    a=parser.parse_args()
    install() if a.install else tests()
if __name__=="__main__":main()
