#!/usr/bin/env python3
"""NEWS2 read-only decision and publication reconciliation (no Telegram API).

Works only on authorized NAS when executed as root. Does not expose texts,
identifiers, bot credentials or moderator names.
"""
from pathlib import Path
from collections import Counter
import ast
import json
import os
import re
import time

O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
DIRS={
 'decisions':O/'news_rg_editorial_decisions_v1',
 'private':O/'news_rg_private_multipart_receipts_v1',
 'public':O/'news_rg_publication_receipts_v1',
 'staged':O/'news_rg_private_review_staging',
}
class Unsafe(Exception):pass

def load(p,limit=32000):
    if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=limit:
        raise Unsafe('FILE_UNSAFE')
    x=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(x,dict):raise Unsafe('NOT_OBJECT')
    return x

def read_dir(key):
    p=DIRS[key]
    if p.is_symlink() or not p.is_dir():raise Unsafe('DIRECTORY_UNSAFE_'+key)
    return p

def reconcile():
    read_dir('decisions');read_dir('private');read_dir('public');read_dir('staged')
    dcounts=Counter(); problems=Counter(); pending=Counter()
    newest=0
    now=time.time()
    total=0
    for p in DIRS['decisions'].glob('*.json'):
        total+=1
        try:
            if not re.fullmatch(r'[a-f0-9]{24}\.json',p.name):
                problems['unexpected_filename']+=1;continue
            d=load(p)
            choice=d.get('decision')
            if choice not in ('editorially_accepted_not_published','editorially_rejected'):
                problems['unexpected_decision']+=1;continue
            if d.get('draft_id')!=p.stem:
                problems['draft_mismatch']+=1;continue
            dcounts[choice]+=1
            newest=max(newest,p.stat().st_mtime)
            if choice!='editorially_accepted_not_published':continue
            public_path=DIRS['public']/p.name
            if public_path.is_symlink():problems['unsafe_public_receipt']+=1;continue
            if public_path.is_file():
                pub=load(public_path)
                pending['accepted_with_public_receipt_'+str(pub.get('status','UNKNOWN'))[:50]]+=1
            else:
                timestamp=d.get('timestamp')
                if isinstance(timestamp,(int,float)):
                    age=now-float(timestamp)
                    key=('under_15m' if age<900 else '15_to_35m' if age<2100 else '35m_to_24h' if age<86400 else 'over_24h')
                    pending['accepted_without_public_receipt_'+key]+=1
                else:pending['accepted_without_public_receipt_unknown_age']+=1
        except (OSError,ValueError,UnicodeError,TypeError,Unsafe):
            problems['decision_read_error']+=1
    return {
      'schema':'NEWS2_DECISIONS_RECONCILE_READONLY_V1',
      'decision_files':total,
      'decision_counts':dict(dcounts),
      'decision_parse_issues':dict(problems),
      'accepted_publication_reconciliation':dict(pending),
      'latest_decision_age_minutes':round((now-newest)/60,1) if newest else None,
      'read_only':True,'telegram_calls':0,'publications':0,'production_writes':0
    }

def selftest():
    sample={'decision':'editorially_accepted_not_published','draft_id':'a'*24}
    assert sample['decision'] in ('editorially_accepted_not_published','editorially_rejected')
    assert re.fullmatch(r'[a-f0-9]{24}\.json','a'*24+'.json')
    assert not re.fullmatch(r'[a-f0-9]{24}\.json','../../anything.json')
    print('NEWS2_DECISION_RECONCILIATION_SELFTEST_PASS')

if __name__=='__main__':
    import sys
    if sys.argv[1:]==['selftest']:
        selftest()
    elif sys.argv[1:]==['inspect']:
        if os.geteuid()!=0:
            print(json.dumps({'status':'SAFE_STOP','reason':'ROOT_REQUIRED'}));sys.exit(2)
        try:print(json.dumps(reconcile(),sort_keys=True))
        except (OSError,Unsafe,ValueError) as e:
            print(json.dumps({'status':'SAFE_STOP','error_class':type(e).__name__,'read_only':True}));sys.exit(2)
    else:raise SystemExit(2)
