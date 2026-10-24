#!/usr/bin/env python3
"""P35 News2 single-update & callback-confirmation audit, read-only, no credentials."""
import datetime, hashlib, json, os, pathlib, sys
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
T=datetime.datetime.now(datetime.timezone.utc)
def safe_age(p):return int(T.timestamp()-p.stat().st_mtime)
def classify(a):
 q=a.get('callback_query')
 if not isinstance(q,dict):return None
 m=q.get('message') or {}
 chat=m.get('chat') or {}
 data=str(q.get('data',''))
 if data.startswith('rgprobe25:'):action='test'
 elif data.startswith('rg3:'):action='moderation:'+data.split(':',2)[1]
 else:action='other'
 return {'update_id':a.get('update_id'),'message_id':m.get('message_id'),'action':action,
  'private_chat':chat.get('type')=='private',
  'moderator_actor_is_bot':(q.get('from') or {}).get('is_bot'),
  'source_bot_username':(m.get('from') or {}).get('username')}
def main():
 if os.geteuid()!=0:
  print(json.dumps({'status':'P35_BLOCKED','reason':'SUDO_REQUIRED'}));return
 state_file=O/'callback_v29_state.json'
 state=json.loads(state_file.read_text()) if state_file.is_file() else {}
 worker=O/'rg_news2_p31_guarded_callback_once.py'
 probation=O/'callback_v29.py'
 archives=sorted(O.glob('updates_handoff_guarded_*.json'))
 last_events=[]
 for path in archives[-250:]:
  try:j=json.loads(path.read_text('utf-8'))
  except Exception:continue
  for item in j.get('updates',[]):
   if not isinstance(item,dict):continue
   c=classify(item)
   if c is not None:
    c['archive']=path.name
    c['archive_age_sec']=safe_age(path)
    last_events.append(c)
 log=O/'callback_v29.log'
 parsed=[]
 if log.is_file():
  with log.open('rb') as f:
   size=f.seek(0,2)
   if size>80000:f.seek(-80000,2)
   else:f.seek(0)
   for ln in f.read().decode('utf-8',errors='replace').splitlines():
    try:j=json.loads(ln)
    except Exception:continue
    if not str(j.get('status','')).startswith('V29_'):continue
    if j.get('updates',0) or j.get('status') not in ('V29_POLL_PASS',):
     parsed.append({'status':j.get('status'),'attempt':j.get('attempts'),
      'updates':j.get('updates'),'outcomes':j.get('outcomes'),'error_class':j.get('error_class')})
 result={'status':'NEWS2_P35_CALLBACK_399_FORENSICS_READONLY',
  'utc':T.isoformat(),
  'callback_state':{'attempts':state.get('attempts'),'successes':state.get('successes'),
    'halt':state.get('halt'),'last_poll':state.get('last_poll_utc'),
    'offset':state.get('last_offset'),'last_result':state.get('last')},
  'newest_events':last_events[-8:],
  'target_399':next((x for x in reversed(last_events) if x.get('update_id')==615861399),None),
  'callback_nonzero_or_failed_logs':parsed[-10:],
  'installed_worker':{'present':worker.is_file(),
   'size_bytes':worker.stat().st_size if worker.is_file() else None,
   'has_visible_test_confirmation':('TEST_BUTTON_VISIBLE_CONFIRMATION_SENT' in worker.read_text('utf-8') if worker.is_file() else False)},
  'installed_probation':{'present':probation.is_file(),
   'logs_visible_failure':('TEST_BUTTON_VISIBLE_REPLY_FAILED' in probation.read_text('utf-8') if probation.is_file() else False)},
  'telegram_api_calls':0,'changes':0,'channel_sends':0}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
