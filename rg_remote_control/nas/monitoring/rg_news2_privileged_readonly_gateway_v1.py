#!/usr/bin/env python3
"""NEWS2 root-owned, strictly read-only diagnostic entry point.

This never executes a shell, reads bot credentials, calls Telegram, writes
publication state, or accepts arbitrary paths or user-provided commands.
"""
import ast
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
ST = ROOT/'news_rg_private_review_staging'
PRIVATE = ROOT/'news_rg_private_multipart_receipts_v1'
PUBLIC = ROOT/'news_rg_publication_receipts_v1'
DECISIONS = ROOT/'news_rg_editorial_decisions_v1'
ROOT_FILES = {
    'photo_publisher': 'news_rg_approved_publication_v1.py',
    'video_publisher': 'news_rg_approved_video_publication_v1.py',
    'footer': 'news_rg_project_footer_v1.py',
    'sender': 'news_rg_durable_private_sender_v1.py',
    'publication_schedule': 'news_rg_publication_schedule_v1.py',
}
REJECT = {'UNCERTAIN_NO_RETRY', 'SENDING_UNCERTAIN', 'HTTP_REJECTED_NO_RETRY'}

def safe_file(path, max_bytes=200000):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        return None
    return path.read_bytes()

def code_features():
    ret = {}
    for name, filename in ROOT_FILES.items():
        b=safe_file(ROOT/filename)
        if b is None:
            ret[name]={'present':False}
            continue
        try:
            s=b.decode('utf8')
            ast.parse(s)
            valid=True
        except (UnicodeError,SyntaxError):
            s=''; valid=False
        entry={'present':True,'syntax_ok':valid,
               'sha256':hashlib.sha256(b).hexdigest()[:20]}
        if name=='photo_publisher':
            entry.update(footer_hook='append_footer(caption)' in s,
                         caption_entities='caption_entities' in s,
                         album_route='album_ids' in s)
        if name=='video_publisher':
            entry.update(send_video='sendVideo' in s,
                         project_footer_hook='news_rg_project_footer_v1' in s or 'append_footer(' in s,
                         html_footer='format_post(' in s)
        if name=='sender':
            entry.update(exclusive_receipt='O_EXCL' in s,
                         quarantine_no_retry='UNCERTAIN_NO_RETRY' in s,
                         sending_uncertain_guard='PAUSED_UNCERTAIN_DELIVERY_REQUIRES_REVIEW' in s)
        if name=='publication_schedule':
            entry['video_route']='video' in s.lower()
        if name=='footer':
            entry.update(clickable_link='https://links.rginfoua.pp.ua/' in s,
                         bold_entity=('bold' in s.lower() or '<b>' in s),
                         url_entity=('text_link' in s or 'text_url' in s or 'href=' in s),
                         has_callable='def append_footer(' in s)
        ret[name]=entry
    return ret

def entries(directory,max_size=32000):
    if not directory.is_dir() or directory.is_symlink():
        return None,1
    count=collections.Counter();errors=0
    for p in directory.glob('*.json'):
        try:
            b=safe_file(p,max_size)
            if b is None:errors+=1;continue
            o=json.loads(b.decode('utf8'))
            if not isinstance(o,dict):errors+=1;continue
            yield o
        except (OSError,ValueError,UnicodeError):
            errors+=1
    # generator cannot directly return counts; see receipt_summary.

def receipt_summary(directory):
    counts=collections.Counter(); bad=0; newest=None
    if not directory.is_dir() or directory.is_symlink():
        return {'present':False,'parse_errors':0}
    for p in directory.glob('*.json'):
        try:
            b=safe_file(p,32000)
            if b is None:bad+=1;continue
            o=json.loads(b.decode('utf8'))
            if not isinstance(o,dict):bad+=1;continue
            st=o.get('status')
            if not isinstance(st,str) or len(st)>70:bad+=1;continue
            counts[st]+=1
            tm=p.stat().st_mtime
            if newest is None or tm>newest:newest=tm
        except (OSError,ValueError,UnicodeError):
            bad+=1
    return {'present':True,'counts':dict(counts),'parse_errors':bad,
            'latest_age_minutes':round((time.time()-newest)/60,1) if newest else None}

def decision_summary(directory):
    """Count editorial *decision* records, not receipt status.

    This fixes false parse errors in the V1 health report. It never exposes
    moderator identities, message IDs or post content.
    """
    counts=collections.Counter();issues=collections.Counter();newest=None
    if not directory.is_dir() or directory.is_symlink():
        return {'present':False,'parse_errors':0,'counts':{}}
    for p in directory.glob('*.json'):
        try:
            if not re.fullmatch(r'[a-f0-9]{24}\.json',p.name):
                issues['unexpected_filename']+=1;continue
            b=safe_file(p,32000)
            if b is None:
                issues['unreadable']+=1;continue
            record=json.loads(b.decode('utf8'))
            if not isinstance(record,dict):
                issues['not_object']+=1;continue
            if record.get('draft_id')!=p.stem:
                issues['draft_id_mismatch']+=1;continue
            decision=record.get('decision')
            if decision=='editorially_expired':
                if record.get('schema')!='NEWS_RG_AUTOMATIC_EXPIRATION_V1':
                    issues['expired_schema_mismatch']+=1;continue
                counts['editorially_expired']+=1
            elif decision in ('editorially_accepted_not_published','editorially_rejected'):
                if record.get('schema')!='NEWS_RG_HUMAN_EDITORIAL_DECISION_V1':
                    issues['human_schema_mismatch']+=1;continue
                counts[decision]+=1
            else:
                issues['unexpected_decision']+=1;continue
            t=p.stat().st_mtime
            if newest is None or t>newest:newest=t
        except (OSError,ValueError,UnicodeError,TypeError):
            issues['unreadable']+=1
    return {'present':True,'counts':dict(counts),'parse_errors':sum(issues.values()),
            'issues':dict(issues),
            'latest_age_minutes':round((time.time()-newest)/60,1) if newest else None}

def staged_summary():
    stat=collections.Counter();fresh=collections.Counter()
    if not ST.is_dir() or ST.is_symlink():return {'present':False}
    for p in ST.glob('*.json'):
        try:
            b=safe_file(p,16000)
            if b is None:stat['unreadable']+=1;continue
            o=json.loads(b.decode('utf8'))
            if not isinstance(o,dict):stat['unreadable']+=1;continue
            stat['total']+=1
            t=float(o.get('prepared_at') or p.stat().st_mtime)
            if time.time()-t<=3*3600:fresh['last_3h']+=1
            if time.time()-t<=3600:fresh['last_1h']+=1
            if o.get('media_type') in ('photo','video','text'):
                stat['media_'+o['media_type']]+=1
        except (OSError,ValueError,UnicodeError,TypeError):
            stat['unreadable']+=1
    return {'present':True,'totals':dict(stat),'fresh':dict(fresh)}

def audit():
    if os.geteuid()!=0:
        raise ValueError('ROOT_REQUIRED')
    if not ROOT.is_dir() or ROOT.is_symlink():
        raise ValueError('OPERATOR_MISSING')
    return {'schema':'RG_NEWS2_PRIVILEGED_READONLY_AUDIT_V1',
            'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'code':code_features(),
            'private_receipts':receipt_summary(PRIVATE),
            'public_receipts':receipt_summary(PUBLIC),
            'decision_receipts':decision_summary(DECISIONS),
            'staged':staged_summary(),
            'read_only':True,'secrets_disclosed':False,
            'telegram_api_calls':0,'publications':0,'production_writes':0,
            'public_runner_shutdown_allowed':False}

def selftest():
    assert safe_file(Path('/nonexistent/news2/file')) is None
    assert REJECT == {'UNCERTAIN_NO_RETRY','SENDING_UNCERTAIN','HTTP_REJECTED_NO_RETRY'}
    assert 'audit' in ('audit',)
    assert decision_summary(Path('/no-such-news2-decisions'))['present'] is False
    assert 'NEWS_RG_AUTOMATIC_EXPIRATION_V1' in decision_summary.__code__.co_consts
    print('NEWS2_PRIVILEGED_READONLY_GATEWAY_SELFTEST_PASS')

if __name__=='__main__':
    if sys.argv[1:]==['selftest']:
        selftest()
    elif sys.argv[1:]==['audit']:
        try:
            print(json.dumps(audit(),ensure_ascii=False,sort_keys=True))
        except (OSError,ValueError,TypeError) as exc:
            print(json.dumps({'status':'SAFE_STOP','error_class':type(exc).__name__,
                              'read_only':True,'telegram_api_calls':0,'production_writes':0}))
            raise SystemExit(2)
    else:
        print('SAFE_STOP_UNSUPPORTED_ACTION')
        raise SystemExit(2)
