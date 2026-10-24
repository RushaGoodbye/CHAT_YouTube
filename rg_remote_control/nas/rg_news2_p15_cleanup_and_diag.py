#!/usr/bin/env python3
"""RG News2 package 15: stop expired callback cron; read-only cross-check of bot ownership and NAS process health.
No getUpdates, no Telegram send*, no channel publishing, no gate changes.
"""
import collections,datetime,json,os,pathlib,sqlite3,subprocess,sys,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
def iso(x):
 try:return datetime.datetime.fromtimestamp(float(x),datetime.timezone.utc).isoformat()
 except Exception:return None
def safe_run(args,timeout=15):
 try:
  p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout)
  return p.returncode,p.stdout
 except Exception:return 99,''
def load(path):
 try:return json.loads(path.read_text('utf-8'))
 except Exception:return {}
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink():raise RuntimeError('OPERATOR_DIR_UNSAFE')
 report={'status':'RG_NEWS2_P15_CLEANUP_AND_DIAG','checked_utc':iso(time.time()),
 'publication_unmodified':True,'channel_sends':0,'getUpdates_calls':0,
 'moderation_delivery_gate':(B/'MODERATION_DELIVERY_ENABLED').is_file(),
 'publication_gate':(B/'PUBLISH_ENABLED').exists(),
 'nas_exclusive_owner_marker':(B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists(),
 'legacy_cutover_gate':LEG.exists()}
 state=load(O/'callback_probation_state.json')
 report['previous_pilot']={'attempts':state.get('attempts'),'halt':state.get('halt'),
    'last':state.get('last'),'expires_at':iso(state.get('expires_at'))}
 # Remove only the prior expired/failed cron via its pre-existing vetted disable action.
 pilot=O/'callback_probation_v1.py'
 if not pilot.is_file() or pilot.is_symlink():raise RuntimeError('PILOT_SCRIPT_MISSING_STOP')
 if state.get('halt') is None and time.time()<state.get('expires_at',float('inf')):
  raise RuntimeError('PILOT_STILL_ACTIVE_MANUAL_REVIEW_REQUIRED')
 code,out=safe_run(['/usr/bin/python3',str(pilot),'disable'])
 if code!=0:raise RuntimeError('CANNOT_DISABLE_HALTED_PILOT_SAFELY')
 disable=json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
 if disable.get('status')!='PROBATION_DISABLED':raise RuntimeError('PILOT_DISABLE_READBACK_FAILED')
 # On Synology crond will reload after crontab mtime change.
 os.utime('/etc/crontab',None)
 cron=pathlib.Path('/etc/crontab').read_text('utf-8',errors='replace')
 report['old_pilot_cron_removed']=('# RG_NEWS2_CALLBACK_PROBATION_V1' not in cron)
 report['delivery_cron_preserved']=('# RG_NEWS2_OUTBOUND_QUEUE_V1' in cron)
 if not report['old_pilot_cron_removed']:raise RuntimeError('PILOT_CRON_STILL_PRESENT')
 if not report['delivery_cron_preserved']:raise RuntimeError('DELIVERY_CRON_MISSING_ESCALATE')
 report['cleanup']='HALTED_PILOT_CRON_REMOVED'
 # Telegram API methods used below do NOT consume callback updates.
 try:
  sys.path.insert(0,str(B))
  import rg_moderation as m
  bot=m.api('getMe',{})
  hook=m.api('getWebhookInfo',{})
  report['telegram']={'getMe_ok':bool(bot.get('id')),'bot_username':bot.get('username'),
     'webhook_active':bool(hook.get('url')),'pending_update_count':hook.get('pending_update_count'),
     'allowed_updates':hook.get('allowed_updates',[])}
 except Exception as e:report['telegram']={'error_type':type(e).__name__}
 # Metadata-only backlog, no stories, photo IDs or credentials.
 try:
  db=sqlite3.connect('file:'+str(B/'news.sqlite3')+'?mode=ro',uri=True,timeout=5)
  status=db.execute('SELECT status,COUNT(*) FROM candidates GROUP BY status').fetchall()
  report['candidates_by_status']={str(a):int(b) for a,b in status}
  if db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='moderation_dispatch'").fetchone()[0]:
   rows=db.execute("SELECT d.message_id,c.status FROM moderation_dispatch d JOIN candidates c ON d.candidate_id=c.id ORDER BY d.message_id DESC LIMIT 10").fetchall()
   report['moderation_cards']=[{'message_id':int(mid),'status':str(st)} for mid,st in rows]
  off=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  report['saved_offset']=int(off[0]) if off else None
  db.close()
 except Exception as e:report['database_error_type']=type(e).__name__
 # Count zombie parents without exposing process command arguments.
 code,ps=safe_run(['ps','-eo','pid,ppid,stat,comm'])
 if code==0:
  lines=ps.splitlines()[1:]
  procs={}; zombies=collections.Counter()
  for s in lines:
   q=s.strip().split(None,3)
   if len(q)!=4:continue
   pid,ppid,st,comm=q
   procs[pid]=comm
   if st.startswith('Z'):zombies[ppid]+=1
  report['processes']={'count':len(procs),'zombies':sum(zombies.values()),
    'zombie_parents':[{'pid':int(pid),'name':procs.get(pid,'exited'),'count':num} for pid,num in zombies.most_common(5)]}
 # Count watchdogs/legacy schedulers without printing commands (which might contain credentials).
 report['scheduler_markers']=[t for t in ('RG_NEWS2_OUTBOUND_QUEUE_V1','RG_NEWS2_CALLBACK_PROBATION_V1','RG_NEWS2_CALLBACK_PILOT_V1','RG_NEWS2_CALLBACK_SERVICE_V1') if t in cron]
 # Short stdout only; full evidence persisted without leaking token or URLs.
 out=O/'P15_STATUS.json'
 tmp=O/'.P15_STATUS.tmp'
 with open(str(tmp),'w') as f:
  json.dump(report,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 os.chmod(str(tmp),0o600);os.replace(str(tmp),str(out))
 print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'P15_BLOCKED','reason':str(e) if isinstance(e,RuntimeError) else type(e).__name__,
   'channel_sends':0},ensure_ascii=False));sys.exit(1)
