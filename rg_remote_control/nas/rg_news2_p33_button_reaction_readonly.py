#!/usr/bin/env python3
"""RG News2 P33: read-only diagnose why a real Telegram inline button has no visible reaction.
NEVER calls Telegram API, changes cron, writes DB, prints secrets or raw message content.
"""
import ast,datetime,json,os,pathlib,re,sqlite3,sys
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
NOW=datetime.datetime.now(datetime.timezone.utc)
def emit(**kwargs):print(json.dumps(kwargs,ensure_ascii=False,sort_keys=True,indent=2),flush=True)
def age(t):
 try:return max(0,int((NOW-datetime.datetime.fromtimestamp(t,datetime.timezone.utc)).total_seconds()))
 except Exception:return None
def log():
 f=O/'callback_v29.log'
 if not f.is_file():return {'exists':False}
 with f.open('rb') as h:
  n=f.stat().st_size
  if n>120000:h.seek(n-120000)
  rows=h.read().decode('utf-8',errors='replace').splitlines()
 events=[]
 for row in rows:
  try:d=json.loads(row)
  except Exception:continue
  if not isinstance(d,dict):continue
  st=str(d.get('status',''))
  if not st.startswith('V29_'):continue
  out=[str(s)[:140] for s in (d.get('outcomes') or [])][:20]
  events.append({'status':st,'updates':d.get('updates'),'outcomes':out,
   'halted':d.get('halted'),'error_class':d.get('error_class'),
   'attempts':d.get('attempts')})
 nonzero=[x for x in events if (x.get('updates') or 0)>0 or x.get('status')!='V29_POLL_PASS']
 return {'exists':True,'mtime_age_sec':age(f.stat().st_mtime),
  'tail_total':len(events),'latest':events[-4:],
  'nonzero_or_failed':nonzero[-16:]}
def callback_archive():
 files=sorted(O.glob('updates_handoff_guarded_*.json'))[-240:]
 sampled=0;total=0;found=[];maxup=None
 for f in files:
  if not f.is_file() or f.is_symlink():continue
  try:
   val=json.loads(f.read_text('utf-8'))
   updates=val.get('updates',[])
  except Exception:continue
  sampled+=1
  total+=len(updates)
  for u in updates:
   maxup=max(maxup or 0,u.get('update_id',0))
   q=u.get('callback_query') or {}
   data=str(q.get('data',''))
   msg=q.get('message') or {}
   actor=q.get('from') or {}
   ch=msg.get('chat') or {}
   action=data.split(':')[:2]
   found.append({'update_id':u.get('update_id'),
     'message_id':msg.get('message_id'),
     'action_prefix':':'.join(action) if action and action[0] in ('rg3','rgprobe25') else 'OTHER',
     'actor_bot':actor.get('is_bot'),
     'chat_type':ch.get('type'),'archive_file':f.name,
     'archive_mtime_age_sec':age(f.stat().st_mtime)})
 return {'files_examined':sampled,'total_updates':total,
  'latest_updates':found[-25:],'max_seen_update_id':maxup}
def db():
 file=B/'news.sqlite3'
 if not file.is_file():return {'exists':False}
 d=sqlite3.connect('file:'+str(file)+'?mode=ro',uri=True,timeout=8)
 d.row_factory=sqlite3.Row
 try:
  row=d.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  statuses=[dict(r) for r in d.execute("""SELECT d.message_id,d.state AS dispatch_status,c.status AS news_status,c.id AS candidate_id
   FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id
   ORDER BY d.message_id DESC LIMIT 12""")]
  queued=d.execute("""SELECT count(*) FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id
   WHERE d.state IN ('sent','send_uncertain')
   AND c.status IN ('awaiting_photo_review','awaiting_moderation')""").fetchone()[0]
  return {'offset':int(row[0]) if row else None,'last_12_dispatch':statuses,
     'waiting_for_decision':queued,'queue_limit':3,
     'publication_gate_enabled':(B/'PUBLISH_ENABLED').exists()}
 finally:d.close()
def handler():
 p=B/'rg_moderation.py'
 if not p.is_file():return {'source_present':False}
 src=p.read_text('utf-8',errors='replace')
 try:t=ast.parse(src)
 except Exception as ex:return {'source_present':True,'ast_error':type(ex).__name__}
 selected=[]
 for n in ast.walk(t):
  if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
  if n.name not in ('process_callback','send_one','poll_once','api'):continue
  calls=[]
  names=[]
  for x in ast.walk(n):
   if isinstance(x,ast.Call):
    fn=x.func
    if isinstance(fn,ast.Name):v=fn.id
    elif isinstance(fn,ast.Attribute):v=fn.attr
    else:continue
    if v not in calls:calls.append(v)
   if isinstance(x,ast.Constant) and isinstance(x.value,str) and
      x.value in ('recheck','reject','similar','approve',
                  'update_id','callback_query','editMessageReplyMarkup',
                  'editMessageCaption','deleteMessage','answerCallbackQuery')):
    if x.value not in names:names.append(x.value)
  selected.append({'function':n.name,'first_line':n.lineno,'last_line':n.end_lineno,
    'method_calls':calls[:50],'action_literals':names[:30]})
 return {'source_present':True,'selected_handlers':selected}
def state():
 p=O/'callback_v29_state.json'
 if not p.is_file():return {'exists':False}
 d=json.loads(p.read_text('utf-8'))
 return {'exists':True,'attempts':d.get('attempts'),'successes':d.get('successes'),
    'last_result':d.get('last'),'halt':d.get('halt'),
    'last_poll_utc':d.get('last_poll_utc'),'last_update_count':d.get('last_update_count'),
    'last_error_class':d.get('last_error_class')}
def main():
 if os.geteuid()!=0:emit(status='P33_BLOCKED',reason='SUDO_REQUIRED');sys.exit(1)
 emit(status='NEWS2_P33_BUTTON_REACTION_DIAG_READONLY',
  utc=NOW.isoformat(),callback_state=state(),callback_log=log(),
  callback_archives=callback_archive(),database=db(),
  moderation_code=handler(),telegram_api_calls=0,file_changes=0,channel_sends=0)
if __name__=='__main__':main()
