#!/usr/bin/env python3
"""Install RG Shorts V3 without changing public scheduler; guarded NEWS RG release."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
G=O/'news_rg_guarded_release_v1.py'
PIN=O/'news_rg_stability_releases_v1/pinned_release_v1.json'
CORE=O/'rg_shorts_v3.py'
CB=O/'news_rg_editorial_callbacks_v1.py'
DB=O/'rg_shorts_no_repeat_v1.sqlite3'
PREFIX='RG_SHORTS_V3_CALLBACK_BRIDGE'
BEFORE="    q=update.get(\"callback_query\") or {}\n"
INSERT="""    # RG_SHORTS_V3_CALLBACK_BRIDGE: existing update stream, no second poller.
    if str((update.get("callback_query") or {}).get("data","")).startswith("rgs3:"):
        try:
            from rg_shorts_v3 import process_callback as _rg_shorts_v3_cb
            return _rg_shorts_v3_cb(update,cfg)
        except Exception:
            return {"status":"SHORTS_V3_HANDLER_UNAVAILABLE"}
"""

def stop(s):raise RuntimeError(s)
def digest(blob):return hashlib.sha256(blob).hexdigest()
def run(args,timeout=240):
    p=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
    return p

def main():
    if os.geteuid()!=0:stop('SUDO_REQUIRED')
    if sys.version_info<(3,15):stop('PYTHON_315_REQUIRED')
    for p in (G,PIN,CORE,CB,DB):
        if p.is_symlink() or not p.is_file():stop('MISSING_OR_SYMLINK_'+p.name)
    info=json.loads(PIN.read_text())
    spec=importlib.util.spec_from_file_location('news_rg_guarded_release',str(G))
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    keys=list(guard.KEY)
    if set(info['files'])!=set(keys):stop('PINNED_FILES_CHANGED')
    original={}
    for name in keys:
        p=O/name
        if p.is_symlink() or not p.is_file():stop('PINNED_FILE_UNSAFE_'+name)
        content=p.read_bytes()
        if digest(content)!=info['files'][name]:stop('PINNED_DRIFT_'+name)
        original[name]=content
    before=original['news_rg_editorial_callbacks_v1.py'].decode('utf-8')
    if PREFIX in before:
        print(json.dumps({'status':'RG_SHORTS_V3_ALREADY_HOOKED','publications':0}))
        return
    if before.count(BEFORE)!=1:stop('CALLBACK_ANCHOR_NOT_UNIQUE')
    after=before.replace(BEFORE,INSERT+BEFORE,1)
    compile(after,str(CB),'exec')
    # Verify V3 can load without touching production Telegram.
    compile(CORE.read_bytes(),str(CORE),'exec')
    tests=run([sys.executable,str(CORE),'selftest'],30)
    if tests.returncode!=0 or 'RG_SHORTS_V3_SELFTEST_PASS' not in tests.stdout:
        stop('SHORTS_V3_SELFTEST_FAILED:'+tests.stdout[-240:])
    # Snapshot SQLite and protected callbacks before any guarded change.
    backup=O/('rg_shorts_v3_backup_'+time.strftime('%Y%m%d_%H%M%S',time.gmtime()))
    backup.mkdir(mode=0o700)
    with sqlite3.connect(str(DB)) as source,sqlite3.connect(str(backup/'rg_shorts_no_repeat_v1.sqlite3')) as dest:
        source.backup(dest)
    (backup/'news_rg_editorial_callbacks_v1.py').write_bytes(original['news_rg_editorial_callbacks_v1.py'])
    (backup/'pinned_release_v1.json').write_bytes(PIN.read_bytes())
    (backup/'rollback_instructions.txt').write_text(
        'Rollback pinned scripts using news_rg_guarded_release_v1.py archived release, '
        'or stage the backed-up callback with the other 17 pinned modules and run guarded install. '
        'Do not restore SQLite over new publication records.\n',encoding='utf-8')
    pending=[]
    try:
        for name in keys:
            p=O/('.'+name+'.stability_candidate')
            if p.exists() or p.is_symlink():stop('PREEXISTING_STABILITY_CANDIDATE_'+name)
            data=after.encode('utf8') if name=='news_rg_editorial_callbacks_v1.py' else original[name]
            with os.fdopen(os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:
                f.write(data);f.flush();os.fsync(f.fileno())
            pending.append(p)
        installed=run([sys.executable,str(G),'install'],240)
        if installed.returncode!=0 or 'STABLE_RELEASE_INSTALLED' not in installed.stdout:
            stop('GUARDED_RELEASE_REJECTED:'+installed.stdout[-420:]+installed.stderr[-200:])
        fresh=json.loads(PIN.read_text())
        if fresh['files']['news_rg_editorial_callbacks_v1.py']!=digest(after.encode('utf8')):
            stop('PINNED_CALLBACK_CHECKSUM_MISMATCH')
        if CB.read_text()!=after:stop('INSTALLED_CALLBACK_MISMATCH')
        out={'status':'RG_SHORTS_V3_INSTALLED_GUARDED','backup':str(backup),
             'guarded_release':'PASS','existing_news':'PRESERVED',
             'shorts_scheduler':'OFF','publications':0}
        print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    finally:
        for p in pending:
            if p.exists():p.unlink()

if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:500],'publications':0},ensure_ascii=False))
        sys.exit(2)
