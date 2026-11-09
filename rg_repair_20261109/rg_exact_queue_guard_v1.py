"""RG fullstream explicit batch guard, transactional installer and static tests.
No media changes, no worker starts.
"""
from pathlib import Path
import sys, ast,hashlib,json,uuid,time,os,argparse

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
TARGET=APP/"rg_fullstream_batch_v53.py"
BACKUP=DATA/"RG_REPAIR_BACKUPS"
ANCHOR1="    app=Path(app);data=Path(data)\n    results=[]"
REPLACE1="""    app=Path(app);data=Path(data)
    # RG_EXACT_QUEUE_GUARD_V1: refuse to auto-start unrelated old tasks.
    pending_root=data/'fullstream_v2'
    if pending_root.is_dir():
        pending=set()
        for old_request in pending_root.glob('*/queue_request.json'):
            old_stream=old_request.parent.name
            if _STREAM.fullmatch(old_stream) and _read_json(old_request).get('stream')==old_stream:
                status=_read_json(old_request.parent/'status.json')
                if status.get('state')!='STOPPED_BY_USER':
                    pending.add(old_stream)
        unrelated=sorted(pending-set(values))
        if unrelated:
            raise RuntimeError('UNRELATED_PENDING_QUEUE_BLOCKED: '+', '.join(unrelated)
                +'. Зупиніть та очистіть стару чергу перед запуском нової.')
    results=[]"""
ANCHOR2="""    def added(values):
        try:
            result=enqueue_many(values,app=app,data=data)"""
REPLACE2="""    def added(values):
        try:
            chosen=parse_numbers(values)
            requested=', '.join(chosen)
            existing=[]
            base=Path(data)/'fullstream_v2'
            if base.is_dir():
                for old in base.glob('*/queue_request.json'):
                    if _STREAM.fullmatch(old.parent.name) and _read_json(old).get('stream')==old.parent.name:
                        old_status=_read_json(old.parent/'status.json')
                        if old_status.get('state')!='STOPPED_BY_USER':
                            existing.append(old.parent.name)
            unrelated=sorted(set(existing)-set(chosen))
            if unrelated:
                raise RuntimeError('СТОП: у старій черзі залишилися інші стрими: '+', '.join(unrelated)
                    +'. Обробку не запущено.')
            approval=QMessageBox.question(widget,'Підтвердити точні номери стримів',
                'ЗАПУСТИТИ ЛИШЕ ЦІ НОМЕРИ: '+requested+'?\\n'
                'Інші стрими не повинні запускатися. Перевірте номери.',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if approval!=QMessageBox.Yes:
                message.setText('Запуск скасовано: номери не підтверджені.')
                return
            result=enqueue_many(chosen,app=app,data=data)"""

def calc(raw):
    source=raw.decode("utf-8-sig")
    if "RG_EXACT_QUEUE_GUARD_V1" in source:raise RuntimeError("ALREADY_INSTALLED")
    if source.count(ANCHOR1)!=1 or source.count(ANCHOR2)!=1:
        raise RuntimeError("SOURCE_ANCHOR_MISMATCH")
    result=source.replace(ANCHOR1,REPLACE1,1).replace(ANCHOR2,REPLACE2,1)
    if "\r\n" in source:result=result.replace("\n","\r\n")
    ast.parse(result)
    return result.encode("utf-8")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--install",action="store_true")
    args=p.parse_args()
    original=TARGET.read_bytes()
    patched=calc(original)
    print("RGEXACT|STATIC_PATCH|PASS",flush=True)
    print("RGEXACT|BEFORE_SHA|"+hashlib.sha256(original).hexdigest(),flush=True)
    print("RGEXACT|AFTER_SHA|"+hashlib.sha256(patched).hexdigest(),flush=True)
    if not args.install:
        print("RGEXACT|DRY_RUN|PASS_NO_CHANGES",flush=True)
        return
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_FULLSTREAM_WORKER_NO_INSTALL")
    # An open Studio has already imported this module. Do not alter files until closed.
    import subprocess
    ps=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",
        r"@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'rg_studio_main\.py' }).Count"],
        text=True,capture_output=True,timeout=12)
    if ps.returncode!=0 or not ps.stdout.strip().isdigit():raise RuntimeError("STUDIO_PROCESS_QUERY_UNVERIFIED")
    if int(ps.stdout.strip())!=0:raise RuntimeError("STUDIO_OPEN_INSTALL_BLOCKED")
    stamp=time.strftime("%Y%m%d_%H%M%S")
    root=BACKUP/("RG_EXACT_QUEUE_GUARD_V1_"+stamp+"_"+uuid.uuid4().hex[:5])
    root.mkdir(parents=True,exist_ok=False)
    dest=root/TARGET.name
    dest.write_bytes(original)
    if dest.read_bytes()!=original:raise RuntimeError("BACKUP_VERIFY_FAILED")
    temporary=TARGET.with_suffix(".guard_v1.tmp")
    try:
        if TARGET.read_bytes()!=original:raise RuntimeError("CONCURRENT_FILE_CHANGE")
        temporary.write_bytes(patched)
        if temporary.read_bytes()!=patched:raise RuntimeError("STAGING_VERIFY_FAILED")
        os.replace(temporary,TARGET)
        if TARGET.read_bytes()!=patched:raise RuntimeError("POSTINSTALL_VERIFY_FAILED")
        print("RGEXACT|INSTALLED|PASS|BACKUP="+str(root),flush=True)
    except:
        TARGET.write_bytes(original)
        print("RGEXACT|ROLLED_BACK|"+str(root),flush=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
if __name__=="__main__":main()
