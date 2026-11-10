#!/usr/bin/env python3
"""RG Shorts private one-video smoke test. No public posting, no callbacks or polling.

Reuses the V1 SQLite SHA-256 inventory. Every attempted file stays reserved or
uncertain; never automatically resend a candidate after an ambiguous response.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid

O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
B=O.parent
V1=O/'rg_shorts_no_repeat_v1.py'
MAX_BYTES=40*1024*1024
ONE_TEST_GATE=O/'rg_shorts_test_one_v2.json'

def output(status,**data):
    print(json.dumps(dict(status=status,**data),ensure_ascii=False,sort_keys=True),flush=True)

def fail(reason):
    output('SAFE_STOP',reason=reason,publications=0)
    sys.exit(2)

def load_v1():
    if not V1.is_file() or V1.is_symlink():fail('V1_NOT_INSTALLED')
    spec=importlib.util.spec_from_file_location('rg_shorts_no_repeat_v1',V1)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def identity():
    # Read the installed private moderation configuration; never infer a channel.
    sys.path.insert(0,str(O))
    sys.path.insert(0,str(B))
    import rg_moderation
    import news_rg_multipart
    cfg=rg_moderation.config()
    chat=cfg.get('moderation_chat_id')
    if type(chat)!=int or chat<=0:fail('PRIVATE_MODERATION_CHAT_ID_NOT_VERIFIED')
    token=news_rg_multipart.token()
    if not isinstance(token,str) or len(token)<30:fail('PRIVATE_BOT_TOKEN_UNAVAILABLE')
    return chat,token

def gate():
    if ONE_TEST_GATE.is_symlink():fail('TEST_GATE_SYMLINK')
    if ONE_TEST_GATE.exists():
        fail('TEST_ALREADY_CLAIMED_NO_REPEAT')
    # This file is a one-shot lock; it must be created before delivery is attempted.
    fd=os.open(str(ONE_TEST_GATE),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump({'status':'ONE_PRIVATE_TEST_CLAIMED','at':int(time.time())},f)
        f.flush();os.fsync(f.fileno())

def choose(cn,mod):
    rows=cn.execute("SELECT sha256,example_path,size_bytes FROM files "
                    "WHERE state='AVAILABLE' AND size_bytes>0 AND size_bytes<=?",
                    (MAX_BYTES,)).fetchall()
    if not rows:fail('NO_SMALL_ELIGIBLE_MP4')
    start=secrets.randbelow(len(rows))
    for i in range(len(rows)):
        row=rows[(start+i)%len(rows)]
        path=pathlib.Path(row['example_path'])
        if not path.is_file() or path.is_symlink() or path.suffix.lower()!='.mp4':continue
        if not path.resolve().is_relative_to(mod.SOURCE.resolve()):continue
        st=path.stat()
        if st.st_size!=row['size_bytes'] or st.st_size>MAX_BYTES:continue
        if mod.hash_file(path)!=row['sha256']:continue
        return row,path
    fail('NO_VERIFIED_SOURCE_FILE')

def preflight():
    if os.geteuid()!=0:fail('SUDO_REQUIRED')
    mod=load_v1()
    if not mod.DB.is_file():fail('INVENTORY_NOT_READY')
    cn=mod.db_open()
    try:
        row,path=choose(cn,mod)
        chat,_=identity()
        if ONE_TEST_GATE.exists():fail('ONE_TEST_ALREADY_USED')
        output('PRIVATE_TEST_READY',files_available=cn.execute(
            "SELECT COUNT(*) FROM files WHERE state='AVAILABLE' AND size_bytes<=?",
            (MAX_BYTES,)).fetchone()[0],
            selected_size_bytes=row['size_bytes'],source_verified=True,
            chat_type='private',publications=0,history_reconciled_not_required_for_private_test=True)
    finally:cn.close()

def send_one():
    if os.geteuid()!=0:fail('SUDO_REQUIRED')
    mod=load_v1()
    cn=mod.db_open()
    try:
        # Validate all credentials and file bytes before creating the send claim.
        chat,token=identity()
        row,path=choose(cn,mod)
        video=path.read_bytes()
        if len(video)!=row['size_bytes'] or len(video)>MAX_BYTES:fail('SOURCE_SIZE_CHANGED')
        if mod.hashlib.sha256(video).hexdigest()!=row['sha256']:fail('SOURCE_HASH_CHANGED')
        cn.execute('BEGIN IMMEDIATE')
        changed=cn.execute(
            "UPDATE files SET state='RESERVED', reserved_at=?,note=? "
            "WHERE sha256=? AND state='AVAILABLE'",
            (int(time.time()),'PRIVATE_TEST_ATTEMPT',row['sha256'])).rowcount
        if changed!=1:cn.rollback();fail('RESERVATION_RACE')
        cn.execute('INSERT INTO events(sha256,event,at) VALUES(?,?,?)',
                   (row['sha256'],'PRIVATE_TEST_ATTEMPT',int(time.time())))
        cn.commit()
        gate()
        boundary='rgsh'+uuid.uuid4().hex
        caption=('🧪 ТЕСТ SHORTS · РАША ГУДБАЙ\n'
                 'Перевірка випадкового відео з NAS.\n'
                 'НЕ ПУБЛІКУВАТИ. Кнопок публікації немає.')
        parts=[]
        for key,value in (('chat_id',str(chat)),('caption',caption),('supports_streaming','true')):
            parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+
                          '"\r\n\r\n'+value+'\r\n').encode())
        parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="video"; filename="rg_short_test.mp4"\r\n'
                      'Content-Type: video/mp4\r\n\r\n').encode()+video+b'\r\n')
        parts.append(('--'+boundary+'--\r\n').encode())
        body=b''.join(parts)
        req=urllib.request.Request(
            'https://api.telegram.org/bot'+token+'/sendVideo',data=body,
            headers={'Content-Type':'multipart/form-data; boundary='+boundary})
        try:
            with urllib.request.urlopen(req,timeout=90) as resp:
                ack=json.loads(resp.read(100000))
            msg=ack.get('result') if ack.get('ok') is True else None
            if not isinstance(msg,dict) or type(msg.get('message_id'))!=int or int((msg.get('chat') or {}).get('id',0))!=chat:
                raise RuntimeError('PRIVATE_VIDEO_ACK_INVALID')
        except Exception as exc:
            # A timeout, HTTP failure, or a missing reply is never evidence of no delivery.
            cn.execute('BEGIN IMMEDIATE')
            cn.execute("UPDATE files SET state='UNCERTAIN',note=? WHERE sha256=? AND state='RESERVED'",
                       (type(exc).__name__,row['sha256']))
            cn.execute('INSERT INTO events(sha256,event,at,details) VALUES(?,?,?,?)',
                       (row['sha256'],'PRIVATE_TEST_UNCERTAIN',int(time.time()),type(exc).__name__))
            cn.commit()
            output('PRIVATE_TEST_UNCERTAIN_NO_RETRY',sha256=row['sha256'],
                   error_class=type(exc).__name__,publications=0)
            return
        cn.execute('BEGIN IMMEDIATE')
        cn.execute("UPDATE files SET note=? WHERE sha256=? AND state='RESERVED'",
                   ('PRIVATE_TEST_CONFIRMED_MESSAGE_'+str(msg['message_id']),row['sha256']))
        cn.execute('INSERT INTO events(sha256,event,at,details) VALUES(?,?,?,?)',
                   (row['sha256'],'PRIVATE_TEST_CONFIRMED',int(time.time()),str(msg['message_id'])))
        cn.commit()
        output('PRIVATE_TEST_CONFIRMED',sha256=row['sha256'],message_id=msg['message_id'],
               file_name=path.name,publications=0,no_repeat='RESERVED')
    finally:cn.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('preflight','send-one-private-test'))
    args=p.parse_args()
    if args.mode=='preflight':preflight()
    else:send_one()

if __name__=='__main__':
    try:main()
    except (sqlite3.Error,OSError,ValueError,ImportError,RuntimeError) as exc:
        fail(type(exc).__name__)
