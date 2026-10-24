#!/usr/bin/env python3
"""Read-only News2 callback forensics. Never prints secrets or raw messages."""
import datetime,glob,json,os,pathlib,sqlite3,sys,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
def load(p):
 try:return json.loads(p.read_text('utf-8'))
 except Exception:return {}
def stamp(x):
 try:return datetime.datetime.fromtimestamp(float(x),datetime.timezone.utc).isoformat()
 except Exception:return None
def main():
 report={'status':'NEWS2_CALLBACK_FORENSICS_READ_ONLY','time_utc':stamp(time.time()),'no_telegram_api_calls':True,'no_file_changes':True,'channel_sends':0}
 for n in ('MODERATION_DELIVERY_ENABLED','NAS_EXCLUSIVE_OWNER_VERIFIED','PUBLISH_ENABLED'):
  report[n]= (B/n).exists()
 p=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
 report['legacy_cutover_enabled']=p.exists()
 state=load(O/'callback_probation_state.json')
 report['probation']={'present':bool(state),'attempts':state.get('attempts'),'halt':state.get('halt'),'last':state.get('last'),'expiry_utc':stamp(state.get('expires_at')),'expired':time.time()>=state.get('expires_at',0)}
 cr=pathlib.Path('/etc/crontab')
 if cr.is_file():
  entries=[x.strip() for x in cr.read_text('utf-8',errors='replace').splitlines() if 'RG_NEWS2_' in x]
  report['cron_news2_entries']=[x[:400] for x in entries]
 log=O/'callback_probation.log'
 if log.is_file():
  lines=log.read_text('utf-8',errors='replace').splitlines()[-200:]
  clean=[]
  for s in lines:
   try:
    d=json.loads(s)
    clean.append({k:d.get(k) for k in ('status','attempts','updates','reason','channel_sends') if k in d})
   except Exception:continue
  report['last_cron_events']=clean[-12:]
 archives=sorted(O.glob('updates_handoff_*.json'),key=lambda p:p.name)
 counts={'total':len(archives),'with_callbacks':0,'without_callbacks':0,'total_callback_updates':0,'actions':{},'last_archives':[]}
 for p in archives[-300:]:
  d=load(p);u=d.get('updates',[])
  c=[x.get('callback_query') for x in u if isinstance(x,dict) and isinstance(x.get('callback_query'),dict)]
  if c:counts['with_callbacks']+=1
  else:counts['without_callbacks']+=1
  counts['total_callback_updates']+=len(c)
  for q in c:
   action=(q.get('data') or '').split(':')
   k=action[1] if len(action)==3 and action[0]=='rg3' else 'other'
   counts['actions'][k]=counts['actions'].get(k,0)+1
  if len(counts['last_archives'])>=8:counts['last_archives'].pop(0)
  counts['last_archives'].append({'file':p.name,'updates':len(u),'callbacks':len(c),'offset':d.get('input_offset')})
 report['archives']=counts
 dbpath=B/'news.sqlite3'
 report['db_available']=dbpath.is_file()
 if dbpath.is_file():
  try:
   db=sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True,timeout=5);db.row_factory=sqlite3.Row
   tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   if 'moderation_meta' in tables:
    row=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
    report['db_offset']=int(row['value']) if row else None
   if 'moderation_dispatch' in tables:
    report['dispatch_states']=[dict(x) for x in db.execute('SELECT state,COUNT(*) n FROM moderation_dispatch GROUP BY state')]
    report['dispatch_recent']=[{'message_id':x['message_id'],'state':x['state'],'candidate_id_prefix':str(x['candidate_id'])[:8]} for x in db.execute('SELECT candidate_id,message_id,state FROM moderation_dispatch ORDER BY message_id DESC LIMIT 8')]
   if 'candidates' in tables:
    cols={x[1] for x in db.execute('PRAGMA table_info(candidates)')}
    if 'status' in cols:
     report['candidate_states']=[dict(x) for x in db.execute('SELECT status,COUNT(*) n FROM candidates GROUP BY status ORDER BY n DESC LIMIT 20')]
   db.close()
  except Exception as e:report['db_error']=type(e).__name__
 report['conclusion']='Read-only evidence; zero updates alone never proves another poller'
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
