"""Transactional full-stream only Whisper model selection repair. No worker launch."""
import ast,hashlib,json,os,sys,time,uuid
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
NAME="rg_fullstream_auto_v2.py"
BATCH="rg_fullstream_batch_v53.py"
BEFORE="if p.is_dir() and (p/'model.bin').is_file() and (p/'config.json').is_file():ct.append(p)"
AFTER=("if (p.is_dir() and (p/'model.bin').is_file() and (p/'config.json').is_file()\n"
       "                    and (p/'tokenizer.json').is_file()\n"
       "                    and ((p/'vocabulary.json').is_file() or (p/'vocabulary.txt').is_file())):\n"
       "                ct.append(p)  # RG_ASR_WHISPER_ONLY_V1: reject CT2 translation models")
def sha(v):return hashlib.sha256(v).hexdigest()
def log(*v):print("RGASRFIX|"+"|".join(map(str,v)),flush=True)
def run():
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_FULLSTREAM_WORKER_NO_PATCH")
    sources={n:(APP/n).read_bytes() for n in (NAME,BATCH)}
    src=sources[NAME].decode("utf-8-sig")
    nl="\r\n" if "\r\n" in src else "\n"
    repl=AFTER.replace("\n",nl)
    if src.count(BEFORE)!=1:raise RuntimeError("MODEL_SELECTOR_ANCHOR_UNEXPECTED")
    new=src.replace(BEFORE,repl,1).encode("utf-8")
    ast.parse(new.decode(),filename=NAME)
    checksum=sources[BATCH].decode("utf-8-sig")
    oldhash=sha(sources[NAME]);newhash=sha(new)
    if checksum.count(oldhash)!=1:raise RuntimeError("BATCH_SHA_ANCHOR_NOT_UNIQUE")
    changed=checksum.replace(oldhash,newhash,1).encode("utf-8")
    ast.parse(changed.decode(),filename=BATCH)
    targets={NAME:new,BATCH:changed}
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_ASR_WHISPER_ONLY_V1_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True,exist_ok=False)
    for n,orig in sources.items():
        f=backup/n
        f.write_bytes(orig)
        if sha(f.read_bytes())!=sha(orig):raise RuntimeError("BACKUP_NOT_VERIFIED:"+n)
    updated=[]
    try:
        for n in (NAME,BATCH):
            p=APP/n
            if p.read_bytes()!=sources[n]:raise RuntimeError("SOURCE_CONCURRENT_CHANGE:"+n)
            tmp=p.with_name(p.name+".whisperonly.tmp")
            tmp.write_bytes(targets[n])
            if sha(tmp.read_bytes())!=sha(targets[n]):raise RuntimeError("WRITE_VERIFY_FAILED")
            os.replace(tmp,p)
            updated.append(n)
        for n in (NAME,BATCH):
            if sha((APP/n).read_bytes())!=sha(targets[n]):
                raise RuntimeError("INSTALL_VERIFY_FAILED:"+n)
        from rg_fullstream_auto_v2 import _offline_asr_models
        ct,pt=_offline_asr_models()
        log("CANDIDATES",json.dumps([str(x) for x in ct]))
        if not ct or not any("faster-whisper-large-v3" in str(x).lower() for x in ct):
            raise RuntimeError("VALID_LOCAL_LARGE_WHISPER_MISSING")
        if any("m2m100" in str(x).lower() for x in ct):
            raise RuntimeError("TRANSLATION_MODEL_STILL_SELECTED")
        log("PASS","WHISPER_ONLY","BACKUP",str(backup))
    except:
        for n in reversed(updated):
            (APP/n).write_bytes(sources[n])
        log("ROLLBACK","ATTEMPTED",str(backup))
        raise
if __name__=="__main__":run()
