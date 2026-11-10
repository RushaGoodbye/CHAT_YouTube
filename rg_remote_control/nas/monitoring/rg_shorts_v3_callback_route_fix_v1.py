#!/usr/bin/env python3
"""Targeted RG Shorts V3 callback bridge repair. No Telegram API, no polling.

Patches only the existing owner callback allowlist and NE1 dispatch condition.
Backups and syntax verification are required; fail closed on unexpected code.
"""
from pathlib import Path
import hashlib
import json
import os
import py_compile
import sys
import time

O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
TARGET=O/'rg_news2_p31_guarded_callback_once.py'
EDITOR=O/'news_rg_editorial_callbacks_v1.py'
MOD=O.parent/'rg_moderation.py'
BACKUP_DIR=O/'rg_shorts_v3_callback_backups'
MARK='RG_SHORTS_V3_CALLBACK_BRIDGE'
OLD_ALLOW="or val.startswith('ne1:') or val=='rg_news2:test'"
NEW_ALLOW="or val.startswith('ne1:') or val.startswith('rgs3:') or val=='rg_news2:test'"
OLD_ROUTE='str(q.get("data","")).startswith("ne1:")'
NEW_ROUTE='str(q.get("data","")).startswith(("ne1:","rgs3:"))'

def fail(reason):
    print(json.dumps({'status':'SAFE_STOP','reason':reason,'telegram_sends':0,
                      'poll_calls':0,'publications':0},ensure_ascii=False))
    sys.exit(2)

def check():
    for p in (TARGET,EDITOR,MOD):
        if p.is_symlink() or not p.is_file() or p.stat().st_size>200000:
            fail('MISSING_OR_UNSAFE_'+p.name)
    editorial=EDITOR.read_text('utf8')
    mod=MOD.read_text('utf8')
    source=TARGET.read_text('utf8')
    if MARK not in editorial or 'startswith("rgs3:")' not in editorial:
        fail('EDITORIAL_BRIDGE_NOT_INSTALLED')
    if '# NEWS_RG_EDITORIAL_HOOK_V1' not in mod:
        fail('MODERATION_BRIDGE_NOT_INSTALLED')
    if '# NEWS_RG_NE1_OWNER_ROUTE_V1' not in source or 'm.process_callback(u,cfg)' not in source:
        fail('EXPECTED_OWNER_DISPATCH_NOT_FOUND')
    compile(source,str(TARGET),'exec')
    return source

def main():
    if os.geteuid()!=0:fail('SUDO_REQUIRED')
    before=check()
    if NEW_ALLOW in before and NEW_ROUTE in before:
        print(json.dumps({'status':'RG_SHORTS_V3_CALLBACK_ROUTE_ALREADY_FIXED',
                         'telegram_sends':0,'poll_calls':0,'publications':0}))
        return
    if before.count(OLD_ALLOW)!=1 or before.count(OLD_ROUTE)!=1:
        fail('CALLBACK_PATCH_ANCHOR_MISMATCH')
    after=before.replace(OLD_ALLOW,NEW_ALLOW,1).replace(OLD_ROUTE,NEW_ROUTE,1)
    compile(after,str(TARGET),'exec')
    if NEW_ALLOW not in after or NEW_ROUTE not in after:
        fail('PATCH_VERIFICATION_FAILED')
    if len(after)-len(before)>100:
        fail('UNEXPECTED_CHANGE_SIZE')
    if BACKUP_DIR.is_symlink():fail('BACKUP_DIRECTORY_SYMLINK')
    BACKUP_DIR.mkdir(mode=0o700,exist_ok=True)
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    backup=BACKUP_DIR/('rg_news2_p31_guarded_callback_once.'+stamp+'.py')
    with os.fdopen(os.open(str(backup),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:
        f.write(before.encode('utf8'));f.flush();os.fsync(f.fileno())
    temp=TARGET.with_name('.rg_news2_callback_v3_'+str(os.getpid())+'.tmp')
    try:
        with os.fdopen(os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:
            f.write(after.encode('utf8'));f.flush();os.fsync(f.fileno())
        compile(temp.read_text('utf8'),str(temp),'exec')
        if hashlib.sha256(TARGET.read_bytes()).hexdigest()!=hashlib.sha256(before.encode('utf8')).hexdigest():
            fail('CONCURRENT_OWNER_CHANGE')
        os.replace(temp,TARGET)
        current=check()
        if current!=after:
            os.replace(backup,TARGET)
            fail('POST_INSTALL_VERIFY_FAILED_RESTORED')
    finally:
        if temp.exists():temp.unlink()
    print(json.dumps({'status':'RG_SHORTS_V3_CALLBACK_ROUTE_REPAIRED',
                      'backup':str(backup),'old_sha256':hashlib.sha256(before.encode('utf8')).hexdigest(),
                      'new_sha256':hashlib.sha256(after.encode('utf8')).hexdigest(),
                      'telegram_sends':0,'poll_calls':0,'publications':0},ensure_ascii=False))

if __name__=='__main__':main()
