#!/usr/bin/env python3
"""RG News2 P32 current live NAS guard/cron/outbound health, READ ONLY.
No API calls, cron changes, source dump, token lookup, or publication.
"""
import datetime,json,os,pathlib,sqlite3,sys
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator';CR=pathlib.Path('/etc/crontab')
STATE=O/'callback_v29_state.json'
MARK='RG_NEWS2_CALLBACK_PROBATION_V29'
OLD='RG_NEWS2_CALLBACK_PROBATION_V1'
NOW=datetime.datetime.now(datetime.timezone.utc)
def utc(ts):
 try:return datetime.datetime.fromtimestamp(int(ts),datetime.timezone.utc).isoformat()
 except Exception:return None
def lastage(iso):
 try:return max(0,int((NOW-datetime.datetime.fromisoformat(iso)).total_seconds()))
 except Exception:return None
def secret_free_lastlog():
 log=O/'callback_v29.log'
 if not log.is_file() or log.is_symlink():return {'exists':False}
 size=log.stat().st_size
 with log.open('rb') as f:
  if size>150000:f.seek(size-150000)
  txt=f.read(150000).decode('utf-8',errors='replace')
 success=fail=blocks=halts=0;last=''
 for line in txt.splitlines():
  try:d=json.loads(line.strip())
  except Exception:continue
  status=str(d.get('status',''))
  if not status.startswith(('V29_',)):continue
  last=status
  if status=='V29_POLL_PASS':success+=1
  if status=='V29_POLL_FAILED':fail+=1
  if status=='V29_BLOCKED':blocks+=1
  if status in ('V29_HALTED','V29_EXPIRED_CRON_REMOVED'):halts+=1
 mtime=datetime.datetime.fromtimestamp(log.stat().st_mtime,datetime.timezone.utc)
 return {'exists':True,'size_bytes':size,'mtime_utc':mtime.isoformat(),
  'mtime_age_sec':int((NOW-mtime).total_seconds()),
  'recent_tail_passes':success,'recent_tail_failures':fail,
  'recent_tail_blocked':blocks,'recent_tail_halts':halts,
  'last_status_in_tail':last}
def cron():
 if not CR.is_file():return {'exists':False}
 rows=CR.read_text('utf-8',errors='replace').splitlines()
 active=[r for r in rows if r.strip() and not r.lstrip().startswith('#')]
 p=[r for r in active if MARK in r]
 outbound=[r for r in active if 'RG_NEWS2_OUTBOUND_QUEUE_V1' in r]
 old=[r for r in active if OLD in r]
 return {'exists':True,'v29_lines':len(p),'v29_every_minute':len(p)==1 and p[0].split()[:5]==['*']*5,
  'v29_root_user':len(p)==1 and p[0].split()[5]=='root',
  'old_callback_cron_lines':len(old),'outbound_cron_lines':len(outbound),
  'outbound_every_5_minutes':len(outbound)==1 and outbound[0].split()[:5]==['*/5','*','*','*','*']}
def state():
 try:
  if STATE.is_symlink():return {'exists':True,'error':'SYMLINK'}
  d=json.loads(STATE.read_text('utf-8'))
 except FileNotFoundError:return {'exists':False}
 except Exception as e:return {'exists':True,'error_type':type(e).__name__}
 age=lastage(d.get('last_poll_utc'))
 return {'exists':True,'started_utc':utc(d.get('started_at')),
  'expires_utc':utc(d.get('expires_at')),
  'attempts':d.get('attempts'),'successes':d.get('successes'),'failures':d.get('failures'),
  'last_result':d.get('last'),'last_poll_utc':d.get('last_poll_utc'),
  'age_since_last_poll_sec':age,'last_update_count':d.get('last_update_count'),
  'last_offset':d.get('last_offset'),'last_error_class':d.get('last_error_class'),
  'halt':d.get('halt'),'cron_activity_confirmed':bool(age is not None and age<=180 and d.get('attempts',0)>=3),
  'schedule_may_be_stalled':bool(age is not None and age>180 and not d.get('halt')),
  'expires_in_days':round((int(d.get('expires_at',0))-NOW.timestamp())/86400,2)}
def db():
 p=B/'news.sqlite3'
 if not p.is_file():return {'exists':False}
 try:
  db=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True,timeout=8)
  db.row_factory=sqlite3.Row
  status={str(r['status']):r['n'] for r in db.execute('SELECT status,count(*) AS n FROM candidates GROUP BY status')}
  queue=[dict(r) for r in db.execute('SELECT c.status as candidate_status,d.state AS dispatch_state,count(*) AS n FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id GROUP BY c.status,d.state')]
  num=db.execute("""SELECT count(*) FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id WHERE d.state IN ('sent','send_uncertain') AND c.status IN ('awaiting_moderation','awaiting_photo_review')""").fetchone()[0]
  off=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  db.close()
  return {'exists':True,'candidate_counts':status,'dispatch_counts':queue,
   'unresolved_moderation_cards':num,'cards_limit':3,
   'headroom':max(0,3-num),'offset':int(off[0]) if off else None}
 except Exception as e:return {'exists':True,'error_type':type(e).__name__}
def process_names():
 matched=[]
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   s=(p/'comm').read_text('utf-8').strip()
  except Exception:continue
  if s in ('crond','cron','synocrond'):
   matched.append(s)
 return sorted(set(matched))
def main():
 if os.geteuid()!=0:
  print(json.dumps({'status':'P32_BLOCKED','reason':'SUDO_REQUIRED'}));sys.exit(1)
 c=cron();s=state();q=db();lg=secret_free_lastlog()
 problems=[]
 if not c.get('v29_every_minute') or not c.get('v29_root_user'):
  problems.append('EXPECTED_MINUTE_CALLBACK_CRON_NOT_FOUND')
 if c.get('old_callback_cron_lines'):problems.append('DUPLICATE_OLD_CALLBACK_CRON')
 if not c.get('outbound_every_5_minutes'):problems.append('OUTBOUND_QUEUE_CRON_MISSING_OR_CHANGED')
 if s.get('halt'):problems.append('CALLBACK_PROBATION_HALTED')
 if s.get('schedule_may_be_stalled'):problems.append('CALLBACK_LAST_TICK_STALE')
 if s.get('attempts',0)<3:problems.append('CRON_AUTONOMY_NOT_YET_VERIFIED')
 if not lg.get('exists'):problems.append('SCHEDULED_CALLBACK_LOG_ABSENT')
 if q.get('unresolved_moderation_cards',0)>3:problems.append('MODERATION_QUEUE_OVER_CAPACITY')
 if (B/'PUBLISH_ENABLED').exists():problems.append('PUBLICATION_GATE_ENABLED_UNEXPECTEDLY')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():problems.append('MODERATION_DELIVERY_GATE_MISSING')
 print(json.dumps({
  'status':'NEWS2_P32_AUTONOMOUS_CALLBACK_AUDIT',
  'utc':NOW.isoformat(),'cron':c,'callback_state':s,'callback_log':lg,
  'database':q,'cron_process_names':process_names(),
  'publication_gate_enabled':(B/'PUBLISH_ENABLED').exists(),
  'issues':problems,'fully_verified':len(problems)==0 and bool(s.get('cron_activity_confirmed')),
  'telegram_api_calls':0,'file_changes':0,'publication_sends':0},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
