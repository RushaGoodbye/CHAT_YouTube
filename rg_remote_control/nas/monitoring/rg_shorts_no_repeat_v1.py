#!/usr/bin/env python3
"""RG Shorts: NAS-only inventory and at-most-once selection. No Telegram network operations.

Historical channel reconciliation must be explicitly completed before selection.
When a reservation becomes uncertain it is NEVER automatically released.
"""
import argparse
import hashlib
import json
import os
import pathlib
import secrets
import sqlite3
import sys
import time

SOURCE = pathlib.Path('/volume1/@appdata/ContainerManager/all_shares/RushaGoodbye/ШОРТС С ТИТРАМИ')
DB = pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator/rg_shorts_no_repeat_v1.sqlite3')
EXT = {'.mp4'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  sha256 TEXT PRIMARY KEY,
  example_path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'AVAILABLE'
    CHECK(state IN ('AVAILABLE','RESERVED','PUBLISHED','UNCERTAIN','HISTORICAL')),
  reserved_at INTEGER,
  published_at INTEGER,
  telegram_message_id INTEGER,
  note TEXT
);
CREATE TABLE IF NOT EXISTS paths (
  path TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL REFERENCES files(sha256)
);
CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT NOT NULL,
  event TEXT NOT NULL,
  at INTEGER NOT NULL,
  details TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_message_per_file ON files(telegram_message_id)
 WHERE telegram_message_id IS NOT NULL;
"""

def fail(msg):
    print(json.dumps({'status':'SAFE_STOP','reason':msg},ensure_ascii=False))
    sys.exit(2)

def db_open():
    if DB.is_symlink(): fail('DATABASE_SYMLINK')
    if not DB.parent.is_dir(): fail('DATABASE_PARENT_MISSING')
    cn=sqlite3.connect(DB,timeout=60)
    cn.row_factory=sqlite3.Row
    cn.execute('PRAGMA busy_timeout=60000')
    cn.execute('PRAGMA foreign_keys=ON')
    cn.executescript(SCHEMA)
    os.chmod(DB,0o600)
    return cn

def hash_file(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for piece in iter(lambda:f.read(4*1024*1024),b''):
            h.update(piece)
    return h.hexdigest()

def scan(cn):
    if not SOURCE.is_dir() or SOURCE.is_symlink():fail('SOURCE_NOT_AVAILABLE_OR_SYMLINK')
    now=int(time.time()); total=0; errors=0; alias=0
    for p in SOURCE.rglob('*'):
        try:
            if not p.is_file() or p.is_symlink() or p.suffix.lower() not in EXT:continue
            first=p.stat(); key=hash_file(p); final=p.stat()
            if first.st_size!=final.st_size or first.st_mtime_ns!=final.st_mtime_ns:
                errors+=1;continue
            rp=str(p.resolve(strict=True)); total+=1
            cn.execute('BEGIN IMMEDIATE')
            prior=cn.execute('SELECT sha256 FROM paths WHERE path=?',(rp,)).fetchone()
            if prior and prior['sha256']!=key:
                cn.execute('DELETE FROM paths WHERE path=?',(rp,))
            existing=cn.execute('SELECT 1 FROM files WHERE sha256=?',(key,)).fetchone()
            if existing:alias+=1
            cn.execute('INSERT INTO files(sha256,example_path,size_bytes,first_seen,last_seen) VALUES(?,?,?,?,?) '
                       'ON CONFLICT(sha256) DO UPDATE SET last_seen=excluded.last_seen,example_path=excluded.example_path',
                       (key,rp,final.st_size,now,now))
            cn.execute('INSERT INTO paths(path,sha256) VALUES(?,?) ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256',(rp,key))
            cn.commit()
        except (OSError,sqlite3.Error):
            cn.rollback();errors+=1
    print(json.dumps({'status':'INVENTORY_COMPLETE','files_scanned':total,'duplicate_paths_seen':alias,
                      'read_errors':errors,'database':str(DB),'published_or_reserved_unchanged':True,
                      'publications':0},ensure_ascii=False))
    if errors:sys.exit(2)

def status(cn):
    states={r['state']:r['n'] for r in cn.execute('SELECT state,COUNT(*) n FROM files GROUP BY state')}
    records=cn.execute('SELECT COUNT(*) FROM paths').fetchone()[0]
    historical=cn.execute("SELECT value FROM config WHERE key='history_reconciled'").fetchone()
    print(json.dumps({'status':'READY_FOR_SELECTION' if historical and historical['value']=='yes' else 'HISTORY_RECONCILIATION_REQUIRED',
                      'states':states,'indexed_paths':records,'history_reconciled':bool(historical and historical['value']=='yes'),
                      'publications':0},ensure_ascii=False))

def reserve(cn):
    cn.execute('BEGIN IMMEDIATE')
    historical=cn.execute("SELECT value FROM config WHERE key='history_reconciled'").fetchone()
    if not historical or historical['value']!='yes': cn.rollback();fail('HISTORICAL_RECONCILIATION_REQUIRED')
    choices=cn.execute("SELECT sha256,example_path FROM files WHERE state='AVAILABLE' AND last_seen >= ?",(int(time.time())-86400*7,)).fetchall()
    if not choices:cn.rollback();fail('NO_NEW_SHORTS')
    chosen=choices[secrets.randbelow(len(choices))]
    sha=chosen['sha256'];path=pathlib.Path(chosen['example_path'])
    if not path.is_file() or path.is_symlink():cn.rollback();fail('SELECTED_FILE_MISSING')
    if hash_file(path)!=sha:cn.rollback();fail('SELECTED_FILE_CHANGED')
    now=int(time.time())
    updated=cn.execute("UPDATE files SET state='RESERVED',reserved_at=? WHERE sha256=? AND state='AVAILABLE'",(now,sha)).rowcount
    if updated!=1:cn.rollback();fail('CONCURRENT_RESERVATION')
    cn.execute('INSERT INTO events(sha256,event,at) VALUES(?,?,?)',(sha,'RESERVED',now))
    cn.commit()
    print(json.dumps({'status':'RESERVED_NOT_SENT','sha256':sha,'path':str(path),
                      'publications':0,'note':'Do not release reservation after unclear Telegram send'},ensure_ascii=False))

def update_status(cn,sha,action,message_id=None):
    if not sha or not len(sha)==64 or not all(c in '0123456789abcdef' for c in sha):fail('INVALID_HASH')
    cn.execute('BEGIN IMMEDIATE')
    row=cn.execute('SELECT state FROM files WHERE sha256=?',(sha,)).fetchone()
    if row is None:cn.rollback();fail('HASH_NOT_IN_INVENTORY')
    old=row['state']
    if action=='confirm':
        if old!='RESERVED' or message_id is None or message_id<=0:cn.rollback();fail('CONFIRM_NEEDS_RESERVED_AND_MESSAGE_ID')
        new='PUBLISHED'
    elif action=='uncertain':
        if old!='RESERVED':cn.rollback();fail('UNCERTAIN_NEEDS_RESERVED')
        new='UNCERTAIN'
    elif action=='historical':
        if old!='AVAILABLE':cn.rollback();fail('HISTORICAL_NEEDS_AVAILABLE')
        new='HISTORICAL'
    else:cn.rollback();fail('BAD_ACTION')
    now=int(time.time())
    cn.execute('UPDATE files SET state=?,published_at=CASE WHEN ?="PUBLISHED" THEN ? ELSE published_at END,telegram_message_id=COALESCE(?,telegram_message_id) WHERE sha256=?',
               (new,new,now,message_id,sha))
    cn.execute('INSERT INTO events(sha256,event,at,details) VALUES(?,?,?,?)',(sha,new,now,str(message_id) if message_id else None))
    cn.commit()
    print(json.dumps({'status':new,'sha256':sha,'message_id':message_id,'publications':0},ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='action',required=True)
    for name in ('scan','status','reserve'):sub.add_parser(name)
    for name in ('confirm','uncertain','historical'):
        p=sub.add_parser(name);p.add_argument('sha256')
        if name=='confirm':p.add_argument('message_id',type=int)
    args=parser.parse_args()
    cn=db_open()
    try:
        if args.action=='scan':scan(cn)
        elif args.action=='status':status(cn)
        elif args.action=='reserve':reserve(cn)
        else:update_status(cn,args.sha256,args.action,getattr(args,'message_id',None))
    finally:cn.close()

if __name__=='__main__':main()
