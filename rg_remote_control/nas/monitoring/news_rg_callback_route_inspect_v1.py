#!/usr/bin/env python3
"""Read-only NEWS RG callback route diagnostic. No Bot API, no getUpdates, no writes."""
import os, pathlib, re, json, ast, sys, time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
V=O/'callback_v29.py'
KEY='e793f4cd55c5246022bf86e8'
MESSAGE=8050
def safe(line):
    line=re.sub(r'\b\d{7,13}:[A-Za-z0-9_-]{20,}\b','<TOKEN_REDACTED>',line)
    if any(x in line.lower() for x in ('secret.read_text','token.read_text','api.telegram.org/bot','password=')):
        return '<SENSITIVE_CODE_REDACTED>'
    return line.strip()[:180]
def code_slice(path):
    text=path.read_text('utf-8')
    lines=text.splitlines()
    needles=('process_callback(', 'def process_callback', 'FOREIGN_CALLBACK_FAMILY',
             'getUpdates', 'ONE_SHOT_CALLBACK_HANDOFF_COMPLETE',
             'callback_query', 'rg3:', 'rgprobe25:', 'ne1:', 'updates_handoff_guarded_')
    relevant=[i for i,l in enumerate(lines) if any(x in l for x in needles)]
    selected=set()
    for i in relevant[:48]:
        for j in range(max(0,i-3),min(len(lines),i+5)):
            selected.add(j)
    return {'name':path.name,'size':len(text),'references':[{'line':i+1,'text':safe(lines[i])} for i in sorted(selected)[:180]],
            'has_ne1':'ne1:' in text,'calls_process_callback':'process_callback(' in text}
def detect_worker():
    text=V.read_text('utf-8')
    result={'callback_v29_name':V.name,'callback_v29_excerpt':[]}
    lines=text.splitlines()
    for i,l in enumerate(lines):
        if 'WORKER' in l and (i<70 or 'def once' in ''.join(lines[max(0,i-5):i])):
            result['callback_v29_excerpt'].append({'line':i+1,'text':safe(l)})
    candidates=[]
    for p in O.glob('*.py'):
        if not p.is_file() or p.is_symlink() or p.stat().st_size>300000:continue
        try:
            s=p.read_text('utf-8')
            if 'updates_handoff_guarded_' in s and 'getUpdates' in s and 'process_callback' in s:
                candidates.append(p)
        except (OSError,UnicodeError):continue
    result['worker_candidates']=[code_slice(p) for p in candidates[:3]]
    return result
def recent_callbacks():
    out=[]
    for p in sorted(O.glob('*updates*.json'),key=lambda x:x.stat().st_mtime,reverse=True)[:60]:
        if not p.is_file() or p.is_symlink() or p.stat().st_size>2000000:continue
        try:
            j=json.loads(p.read_text('utf-8'))
            ups=j.get('updates',[]) if isinstance(j,dict) else []
            for u in ups:
                q=u.get('callback_query') or {}
                data=str(q.get('data',''))
                if data.startswith('ne1:') or KEY in data or (q.get('message') or {}).get('message_id')==MESSAGE:
                    out.append({'archive':p.name,'callback_family':'ne1' if data.startswith('ne1:') else 'other',
                      'message_match':(q.get('message') or {}).get('message_id')==MESSAGE,
                      'update_id':u.get('update_id')})
        except (OSError,ValueError,TypeError):continue
    return out[:10]
if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:
            assert '<TOKEN_REDACTED>' in safe('12345678:'+'a'*35)
            print('NEWS_RG_CALLBACK_ROUTE_INSPECT_SELFTEST_PASS')
        elif sys.argv[1:]==['inspect']:
            if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
            print(json.dumps({'schema':'NEWS_RG_CALLBACK_ROUTE_INSPECT_V1',
                'read_only':True,'telegram_calls':0,'pollers_started':0,'publications':0,
                'route':detect_worker(),'archived_target_callbacks':recent_callbacks()},ensure_ascii=False,indent=2))
        else:raise RuntimeError('UNKNOWN_MODE')
    except Exception as e:
        print(json.dumps({'status':'SAFE_STOP','reason':type(e).__name__,'telegram_calls':0,'publications':0}))
        sys.exit(2)
