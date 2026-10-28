#!/usr/bin/env python3
"""NEWS RG final NAS autonomy evidence audit (strictly read-only).

Does NOT run any scheduler, model, Telegram API or publisher.
No network, no database writes, no lock-file creation, no getUpdates.
Checks DSM tick wiring, task metadata if available, and durable receipts.
A previous manual tick is NOT proof of autonomous publication.
"""
import os,sys,re,json,time,sqlite3,pathlib,subprocess,datetime
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
TICK=BASE/'rg_news_dsm_tick.sh'
PUB=OP/'news_rg_approved_publication_v1.py'
ID='585dbea8f319d9b538910a6d'
PRIVATE_MSG=8053
CHANNEL=-1001755891079
def emit(**kw):print(json.dumps(kw,ensure_ascii=False,sort_keys=True,indent=2))
def safe(p):
 try:return p.is_file() and not p.is_symlink()
 except OSError:return False
def data(p,limit=25000):
 if not safe(p) or p.stat().st_size>limit:return None
 try:
  d=json.loads(p.read_text('utf8'))
  return d if isinstance(d,dict) else None
 except (ValueError,OSError):return None
def minutes(t):
 try:
  t=float(t)
  if not 1600000000<t<time.time()+1800:return None
  return round(max(0,time.time()-t)/60,1)
 except (ValueError,TypeError,OverflowError):return None
def marker(p):
 if not safe(p) or p.stat().st_size>100:return None
 try:return minutes(p.read_text('utf8').strip())
 except OSError:return None
def meta(p):
 if not safe(p):return {'present':False}
 return {'present':True,'age_min':minutes(p.stat().st_mtime),'bytes':p.stat().st_size}
def status_log(p):
 if not safe(p) or p.stat().st_size>10485760:return {'present':safe(p)}
 try:
  with p.open('rb') as f:
   f.seek(max(0,p.stat().st_size-24000))
   lines=f.read().decode('utf8','replace').splitlines()[-12:]
  for line in reversed(lines):
   try:
    d=json.loads(line)
    if isinstance(d,dict):
     return {'present':True,'last_status':str(d.get('status','UNKNOWN'))[:80],
      'last_reason':str(d.get('reason',''))[:80],
      'last_message_id':d.get('message_id') if isinstance(d.get('message_id'),int) else None,
      'age_min':minutes(p.stat().st_mtime)}
   except ValueError:pass
  return {'present':True,'last_status':'NO_JSON_LOG_LINES','age_min':minutes(p.stat().st_mtime)}
 except OSError:return {'present':True,'last_status':'READ_ERROR'}
def shell_wiring():
 if not safe(TICK) or TICK.stat().st_size>40000:return {'status':'TICK_MISSING_OR_UNSAFE'}
 txt=TICK.read_text('utf8',errors='replace')
 markers=[
  ('source_scan','# NEWS_RG_ISOLATED_SCHEDULE_V2','news_rg_safe_schedule_v2.py'),
  ('private_dispatch','# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1','news_rg_private_dispatch_schedule_v1.py'),
  ('approved_publication','# NEWS_RG_APPROVED_PUBLICATION_CUTOVER_V1','news_rg_publication_schedule_v1.py')]
 found={}
 for name,tag,target in markers:
  n=txt.count(tag)
  t=txt.count(target)
  idx=txt.find(tag)
  e=txt.find('exit 0',idx) if idx>=0 else -1
  found[name]={'marker_count':n,'target_count':t,'wired':n==1 and t==1 and idx>=0 and e>idx}
 try:
  r=subprocess.run(['sh','-n',str(TICK)],capture_output=True,timeout=6)
  syntax_ok=r.returncode==0
 except (OSError,subprocess.TimeoutExpired):syntax_ok=False
 # No shell command is executed, only static parse / syntax validation.
 return {'status':'WIRED' if syntax_ok and all(f['wired'] for f in found.values()) else 'CHECK_REQUIRED',
         'shell_syntax_ok':syntax_ok,'hooks':found,
         'executable':bool(TICK.stat().st_mode & 0o111)}
def dsm_task():
 candidates=['/usr/syno/bin/synoschedtask','/usr/syno/sbin/synoschedtask']
 cli=next((p for p in candidates if os.path.isfile(p) and os.access(p,os.X_OK)),None)
 if not cli:return {'status':'DSM_CLI_NOT_FOUND'}
 try:
  p=subprocess.run([cli,'--get','id=4'],capture_output=True,timeout=7)
 except (OSError,subprocess.TimeoutExpired):
  return {'status':'DSM_TASK_QUERY_UNAVAILABLE'}
 if p.returncode!=0:return {'status':'DSM_TASK_QUERY_UNAVAILABLE','rc':p.returncode}
 # The full task definition can contain private commands; never print it.
 raw=p.stdout.decode('utf8','replace')[:40000]
 enabled=bool(re.search(r'(?im)^\s*(?:enabled|enable)\s*[:=]\s*(?:true|1|yes)\b',raw))
 disabled=bool(re.search(r'(?im)^\s*(?:enabled|enable)\s*[:=]\s*(?:false|0|no)\b',raw))
 if re.search(r'rg_news_dsm_tick',raw,re.I):
  match='RG_NEWS_DSM_TICK_PRESENT'
 else:match='TASK_COMMAND_NOT_IDENTIFIABLE'
 return {'status':'DSM_TASK_READ','task_id':4,'task_match':match,
         'enabled':'YES' if enabled else 'NO' if disabled else 'UNKNOWN'}
def sqlite_status():
 p=OP/'news_rg_editorial_shadow_v1.sqlite3'
 if not safe(p):return {'status':'SHADOW_DB_MISSING'}
 try:
  db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=4)
  try:
   db.execute('pragma query_only=ON')
   tables={row[0] for row in db.execute("select name from sqlite_master where type='table'")}
   out={'status':'OK'}
   if 'source_cursor' in tables:
    cols={row[1] for row in db.execute('pragma table_info(source_cursor)')}
    if 'last_scan_at' in cols:
     v=db.execute('select max(last_scan_at),count(*) from source_cursor').fetchone()
     out['last_source_scan_age_min']=minutes(v[0]);out['source_cursor_count']=v[1]
   if 'story_shadow' in tables:
    cols={row[1] for row in db.execute('pragma table_info(story_shadow)')}
    if {'posted_at','status'}.issubset(cols):
     v=db.execute('select max(posted_at),count(*) from story_shadow').fetchone()
     out['latest_source_post_age_min']=minutes(v[0]);out['source_story_count']=v[1]
   return out
  finally:db.close()
 except (OSError,sqlite3.Error) as e:return {'status':'SHADOW_READ_UNAVAILABLE','error_type':type(e).__name__}
def editorial_queue():
 directory=OP/'news_rg_private_multipart_receipts_v1'
 decdir=OP/'news_rg_editorial_decisions_v1'
 if not directory.is_dir() or directory.is_symlink():return {'status':'RECEIPTS_UNAVAILABLE'}
 delivered=0;awaiting=0;newest=None
 for p in directory.glob('*.json'):
  d=data(p)
  if not d or d.get('status')!='PRIVATE_SENT_CONFIRMED':continue
  delivered+=1;newest=max(newest or 0,p.stat().st_mtime)
  decision=data(decdir/p.name)
  if decision is None:awaiting+=1
 return {'status':'OK','private_delivered_total':delivered,
   'awaiting_human_review':awaiting,'latest_private_receipt_age_min':minutes(newest)}
def report():
 approval=data(OP/'news_rg_editorial_decisions_v1'/(ID+'.json'))
 receipt=data(OP/'news_rg_publication_receipts_v1'/(ID+'.json'))
 activation=data(OP/'news_rg_publication_activation_v1.json')
 verified=bool(approval and approval.get('draft_id')==ID and approval.get('telegram_message_id')==PRIVATE_MSG
  and approval.get('decision')=='editorially_accepted_not_published')
 pubok=bool(receipt and receipt.get('draft_id')==ID and receipt.get('status')=='PUBLIC_PUBLISHED_CONFIRMED'
   and receipt.get('channel_id')==CHANNEL and isinstance(receipt.get('message_id'),int))
 wire=shell_wiring()
 output={
  'schema':'NEWS_RG_DSM_AUTONOMY_READONLY_AUDIT_V1',
  'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'read_only':True,'telegram_calls':0,'ai_calls':0,'db_writes':0,'publications_triggered':0,
  'existing_telegram_bot_unchanged':True,
  'dsm_tick':wire,'dsm_task_4':dsm_task(),
  'launch_markers':{
   'source_ai_last_launch_age_min':marker(OP/'news_rg_last_launch_utc'),
   'private_dispatch_last_launch_age_min':marker(OP/'news_rg_private_dispatch_last_launch'),
   'public_dispatch_last_launch_age_min':marker(OP/'news_rg_publication_last_launch')},
  'source_pipeline':sqlite_status(),
  'private_queue':editorial_queue(),
  'logs':{
   'source_ai':status_log(OP/'news_rg_autorun.log'),
   'private_dispatch':status_log(OP/'news_rg_private_dispatch_autorun.log'),
   'public_dispatch':status_log(OP/'news_rg_publication_autorun.log')},
  'card_8053':{
   'accepted_on_NAS':verified,
   'published_to_expected_channel':pubok,
   'public_message_id':receipt.get('message_id') if pubok else None,
   'approval_to_publication_min':round((receipt['published_at']-approval['timestamp'])/60,2) if
      pubok and isinstance(receipt.get('published_at'),int) and
      isinstance(approval.get('timestamp'),int) else None
  },
  'publication_gate_active':bool(activation and activation.get('status')=='ACTIVE' and activation.get('chat_id')==CHANNEL)}
 # The 8053 publication followed a MANUAL shell invocation. Never mislabel it
 # as an independent scheduler proof.
 if not pubok:result='PUBLIC_DELIVERY_NOT_CONFIRMED'
 elif wire.get('status')!='WIRED':result='DSM_TICK_WIRING_REQUIRES_ATTENTION'
 elif not output['publication_gate_active']:result='PUBLICATION_GATE_NOT_ACTIVE'
 else:result='MANUAL_E2E_PASS__UNATTENDED_CYCLE_STILL_NOT_PROVEN'
 output['verdict']=result
 return output
def selftest():
 assert minutes(time.time()-90) is not None
 assert minutes(0) is None
 assert not data(pathlib.Path('/does-not-exist-newsrg.json'))
 assert ID.isalnum() and len(ID)==24
 print('NEWS_RG_DSM_AUTONOMY_READONLY_AUDIT_SELFTEST_PASS')
if __name__=='__main__':
 if sys.argv[1:]==['selftest']:selftest()
 elif sys.argv[1:]==['inspect']:emit(**report())
 else:raise SystemExit('EXPECTED_SELFTEST_OR_INSPECT')
