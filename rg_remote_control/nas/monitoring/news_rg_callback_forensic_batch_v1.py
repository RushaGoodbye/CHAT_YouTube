#!/usr/bin/env python3
"""Read-only NEWS RG callback forensic batch for private message 8050.
No Telegram polling, message sending, database writes or public publication.
"""
import os, sys, json, pathlib, time, collections, sqlite3, importlib.util
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
DRAFT='e793f4cd55c5246022bf86e8'
MESSAGE=8050
def report(**data): print(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2))
def safe_file(p,limit=2000000):
    return p.is_file() and not p.is_symlink() and p.stat().st_size<=limit
def archive_summary():
    files=sorted([p for p in O.glob('*updates*.json') if safe_file(p)],key=lambda p:p.stat().st_mtime,reverse=True)
    counts=collections.Counter(); relevant=[]; newest_id=None; oldest_id=None; decoded=0
    now=time.time()
    for p in files[:200]:
        try:
            obj=json.loads(p.read_text('utf-8'))
            updates=obj.get('updates',[]) if isinstance(obj,dict) else []
            if not isinstance(updates,list): continue
            decoded+=1
            for u in updates:
                if not isinstance(u,dict):continue
                uid=u.get('update_id')
                if isinstance(uid,int):
                    newest_id=uid if newest_id is None else max(uid,newest_id)
                    oldest_id=uid if oldest_id is None else min(uid,oldest_id)
                q=u.get('callback_query') or {}
                if not isinstance(q,dict): continue
                data=q.get('data') or ''
                if not isinstance(data,str):continue
                family=data.split(':')[0] if ':' in data else 'unknown'
                if family not in ('ne1','rg3','ph1','rgprobe25'):family='other'
                counts[family]+=1
                msg=q.get('message') or {}
                if (data.startswith('ne1:') or DRAFT in data or msg.get('message_id')==MESSAGE):
                    relevant.append({'family':family,'draft_match':DRAFT in data,
                     'message_match':msg.get('message_id')==MESSAGE,
                     'update_id':uid,'archive_age_sec':int(now-p.stat().st_mtime)})
        except (OSError,ValueError,TypeError):continue
    return {'files_scanned':decoded,'all_archive_files':len(files),
            'newest_archived_update_id':newest_id,'oldest_archived_update_id':oldest_id,
            'callback_family_counts':dict(counts),'matching_events':relevant[:15]}
def log_summary():
    p=O/'callback_v29.log'
    if not safe_file(p,50000000): return {'exists':False}
    size=p.stat().st_size
    with p.open('rb') as f:
        f.seek(max(0,size-250000))
        content=f.read().decode('utf-8','replace')
    signatures=('FOREIGN_CALLBACK_FAMILY_DETECTED','TELEGRAM_409_POLL_CONFLICT',
                'ONE_SHOT_CALLBACK_HANDOFF_COMPLETE','HANDOFF_BLOCKED','CALLBACK_LOCK_BUSY',
                'NEWS_RG','EDITORIAL','NE1','ERROR','SAFE_STOP','update_count')
    return {'exists':True,'age_sec':int(time.time()-p.stat().st_mtime),
            'last_bytes_scanned':len(content.encode()),
            'markers':{k:content.count(k) for k in signatures if content.count(k)}}
def decision():
    p=O/'news_rg_editorial_decisions_v1'/(DRAFT+'.json')
    if not safe_file(p,5000):return {'status':'NOT_RECORDED'}
    try:
        d=json.loads(p.read_text('utf-8'))
        if d.get('draft_id')!=DRAFT or d.get('telegram_message_id')!=MESSAGE:
            return {'status':'MISMATCH'}
        return {'status':'CONFIRMED','decision':d.get('decision'),'public_publication':d.get('public_publication')}
    except (OSError,ValueError):return {'status':'CORRUPT'}
def offset():
    p=B/'news.sqlite3'
    if not safe_file(p,1000000000):return {'status':'UNAVAILABLE'}
    try:
        c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3)
        try:
            row=c.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
            return {'status':'READ','value':int(row[0]) if row else None}
        finally:c.close()
    except (ValueError,OSError,sqlite3.Error):return {'status':'UNAVAILABLE'}
def webhook():
    p=B/'rg_moderation.py'
    if not safe_file(p,400000):return {'status':'MODULE_UNAVAILABLE'}
    try:
        if str(B) not in sys.path:sys.path.insert(0,str(B))
        sp=importlib.util.spec_from_file_location('_news_rg_preflight_moderator',str(p))
        module=importlib.util.module_from_spec(sp);sp.loader.exec_module(module)
        response=module.api('getWebhookInfo',{})
        return {'status':'OK','webhook_enabled':bool(response.get('url')),
                'pending_update_count':response.get('pending_update_count'),
                'last_error_present':bool(response.get('last_error_message'))}
    except Exception as exc:
        err=str(exc)
        return {'status':'UNAVAILABLE','error_class':err if err in ('TELEGRAM_REQUEST_REJECTED','TELEGRAM_RESPONSE_UNCERTAIN') else type(exc).__name__}
def main():
    if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
    a=archive_summary(); log=log_summary(); d=decision(); off=offset(); wh=webhook()
    route=O/'rg_news2_p31_guarded_callback_once.py'
    routing=bool(route.is_file() and not route.is_symlink() and
        '# NEWS_RG_NE1_OWNER_ROUTE_V1' in route.read_text('utf-8'))
    report(schema='NEWS_RG_CALLBACK_FORENSIC_BATCH_V1',read_only=True,
        telegram_calls=['getWebhookInfo'],getUpdates_calls=0,telegram_sends=0,
        public_publications=0,second_pollers_started=0,
        message_id=MESSAGE,draft_id=DRAFT,decision=d,
        route_installed=routing,archives=a,callback_owner_log=log,
        moderation_offset=off,bot_webhook=wh)
if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:
            assert DRAFT and len(DRAFT)==24 and MESSAGE==8050
            print('NEWS_RG_CALLBACK_FORENSIC_SELFTEST_PASS')
        elif sys.argv[1:]==['audit']:main()
        else:raise RuntimeError('INVALID_COMMAND')
    except Exception as exc:
        print(json.dumps({'status':'SAFE_STOP','error_class':type(exc).__name__,
                         'telegram_sends':0,'public_publications':0}))
        sys.exit(2)
