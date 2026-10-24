#!/usr/bin/env python3
"""RG News2 P29: bounded 7-day automatic moderation callback probation on NAS.
Strictly one existing tested one-shot handler. No publication, no owner claim.
Cron every minute; auto-expire and fail closed on errors/conflicts. Backup cron.
"""
import datetime,fcntl,json,os,pathlib,re,stat,subprocess,sys,tempfile,time,sqlite3
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
CR=pathlib.Path('/etc/crontab')
STATE=O/'callback_v29_state.json'
WORKER=O/'rg_news2_controlled_callback_once_v1.py'
MARK='# RG_NEWS2_CALLBACK_PROBATION_V29'
LINE='* * * * *\troot\t/usr/bin/python3 /volume1/docker/RG_TELEGRAM_NEWS_2/operator/callback_v29.py tick >> /volume1/docker/RG_TELEGRAM_NEWS_2/operator/callback_v29.log 2>&1 '+MARK
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
def emit(**v):print(json.dumps(v,ensure_ascii=False,sort_keys=True),flush=True)
def nowstr():return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
def readstate():
 try:return json.loads(STATE.read_text('utf-8'))
 except FileNotFoundError:return None
def write(path,obj):
 fd,temp=tempfile.mkstemp(dir=str(path.parent),prefix='.rg29_')
 try:
  with os.fdopen(fd,'w') as f:json.dump(obj,f);f.flush();os.fsync(f.fileno())
  os.chmod(temp,0o600);os.replace(temp,str(path))
 finally:
  if os.path.exists(temp):os.unlink(temp)
def cron_update(enable):
 old=CR.read_text('utf-8')
 rows=old.splitlines()
 if any(MARK in x and x!=LINE for x in rows):raise RuntimeError('CRON_MARKER_DRIFT')
 if enable and any('RG_NEWS2_CALLBACK_PROBATION_V1' in x or 'RG_NEWS2_CALLBACK_SERVICE_V1' in x for x in rows):
  raise RuntimeError('OTHER_NEWS2_CALLBACK_CRON_PRESENT')
 new='\n'.join([x for x in rows if MARK not in x]+([LINE] if enable else []))+'\n'
 if old==new:return False
 back=O/('crontab_before_news2_v29_'+nowstr()+'.txt')
 with os.fdopen(os.open(str(back),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
  f.write(old);f.flush();os.fsync(f.fileno())
 meta=CR.stat()
 fd,temp=tempfile.mkstemp(dir=str(CR.parent),prefix='.rg29_cron_')
 try:
  with os.fdopen(fd,'w') as f:f.write(new);f.flush();os.fsync(f.fileno())
  os.chmod(temp,stat.S_IMODE(meta.st_mode));os.chown(temp,meta.st_uid,meta.st_gid)
  os.replace(temp,str(CR))
 finally:
  if os.path.exists(temp):os.unlink(temp)
 if CR.read_text('utf-8')!=new:raise RuntimeError('CRON_VERIFY_FAILED')
 os.utime(str(CR),None)
 return True
def guards():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink() or not CR.is_file() or CR.is_symlink():
  raise RuntimeError('CRON_OR_OPERATOR_UNSAFE')
 if (B/'PUBLISH_ENABLED').exists():raise RuntimeError('CHANNEL_PUBLICATION_GATE_OPEN')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('DELIVERY_GATE_MISSING')
 if (B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():raise RuntimeError('OWNER_MODE_CHANGED')
 if LEG.exists() or LEG.is_symlink():raise RuntimeError('LEGACY_CUTOVER_GATE_OPEN')
 if not WORKER.is_file() or WORKER.is_symlink():raise RuntimeError('KNOWN_CALLBACK_WORKER_MISSING')
 text=WORKER.read_text('utf-8')
 if not all(x in text for x in ('updates_handoff_','process_callback','getUpdates','PUBLISH_ENABLED')):
  raise RuntimeError('CALLBACK_WORKER_SOURCE_CHANGED')
def proof():
 # Do not infer a live moderation decision from an old recheck or a test card.
 p=O/'p30_real_decision_proof.json'
 if not p.is_file() or p.is_symlink():return {'verified':False,'reason':'P30_PROOF_MISSING'}
 try:d=json.loads(p.read_text('utf-8'))
 except Exception:return {'verified':False,'reason':'P30_PROOF_INVALID'}
 if d.get('verified') is not True or d.get('action')!='reject':
  return {'verified':False,'reason':'NO_REAL_REJECT_PROOF'}
 try:
  issued=datetime.datetime.fromisoformat(d['time_utc'])
  age=(datetime.datetime.now(datetime.timezone.utc)-issued).total_seconds()
 except Exception:return {'verified':False,'reason':'INVALID_PROOF_TIME'}
 if age<0 or age>3600:return {'verified':False,'reason':'PROOF_TOO_OLD'}
 mid=d.get('message_id')
 uid=d.get('update_id')
 name=d.get('archive_name','')
 if not isinstance(mid,int) or not isinstance(uid,int) or not re.fullmatch(r'p30_updates_[0-9]{8}T[0-9]{12}Z\.json',name):
  return {'verified':False,'reason':'INVALID_PROOF_REFERENCES'}
 archive=O/name
 if not archive.is_file() or archive.is_symlink():
  return {'verified':False,'reason':'PROOF_ARCHIVE_MISSING'}
 try:
  updates=json.loads(archive.read_text('utf-8')).get('updates',[])
 except Exception:return {'verified':False,'reason':'PROOF_ARCHIVE_BAD'}
 matched=False
 for u in updates:
  if not isinstance(u,dict) or u.get('update_id')!=uid:continue
  q=u.get('callback_query') or {}
  msg=q.get('message') or {}
  parts=str(q.get('data','')).split(':')
  if len(parts)>=3 and parts[0]=='rg3' and parts[1]=='reject' and msg.get('message_id')==mid and (msg.get('chat') or {}).get('type')=='private':
   matched=True;break
 if not matched:return {'verified':False,'reason':'PROOF_ARCHIVE_NO_REAL_REJECT'}
 db=sqlite3.connect('file:'+str(B/'news.sqlite3')+'?mode=ro',uri=True,timeout=5)
 try:
  row=db.execute('SELECT c.status,c.id FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id WHERE d.message_id=?',(mid,)).fetchone()
  saved=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  if not row or str(row[1])!=d.get('candidate_id') or row[0]!=d.get('after') or row[0] in ('awaiting_photo_review','awaiting_moderation'):
   return {'verified':False,'reason':'STATE_DOES_NOT_CONFIRM_DECISION'}
  if not saved or int(saved[0])<=uid:
   return {'verified':False,'reason':'OFFSET_HAS_NOT_ADVANCED'}
  return {'verified':True,'message_id':mid,'update_id':uid,'action':'reject','candidate_status_after':row[0]}
 finally:db.close()
def once():
 p=subprocess.run(['/usr/bin/python3',str(WORKER),'once'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
  universal_newlines=True,timeout=50)
 obj={}
 try:obj=json.loads(p.stdout.strip().splitlines()[-1])
 except Exception:pass
 if p.returncode or obj.get('status')!='ONE_SHOT_CALLBACK_HANDOFF_COMPLETE':
  detail=str(obj.get('reason',''))
  typ='TELEGRAM_409_POLL_CONFLICT' if '409' in detail or 'Conflict' in detail else (
       'HANDOFF_BLOCKED' if obj.get('status')=='BLOCKED' else 'ONESHOT_ERROR')
  return {'pass':False,'error_class':typ}
 return {'pass':True,'updates':int(obj.get('update_count',0)),
    'outcomes':[str(x)[:60] for x in obj.get('outcomes',[])[:25]],
    'offset_after':obj.get('offset_after')}
def lock():
 fd=os.open(str(O/'callback_v29.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except Exception:os.close(fd);raise RuntimeError('ANOTHER_V29_RUNNING')
 return fd
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ('install','tick','status','disable'):
  raise RuntimeError('USE_INSTALL_TICK_STATUS_DISABLE')
 cmd=sys.argv[1]
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if cmd=='status':
  s=readstate()
  emit(status='V29_STATUS',scheduled=MARK in CR.read_text('utf-8'),state=s,
   channel_sends=0,owner_exclusivity_proven=False)
  return
 if cmd=='disable':
  # Emergency disable always allowed, even when publishing gates later changed.
  changed=cron_update(False)
  s=readstate()
  if s:
   s['halt']='operator_disabled';write(STATE,s)
  emit(status='V29_DISABLED',cron_changed=changed,channel_sends=0)
  return
 guards()
 fd=lock()
 try:
  if cmd=='install':
   existing=readstate()
   if existing is not None:
    emit(status='V29_ALREADY_INSTALLED',state_halt=existing.get('halt'),
     scheduled=MARK in CR.read_text('utf-8'));return
   evidence=proof()
   if not evidence.get('verified'):
    raise RuntimeError('REAL_MODERATION_DECISION_NOT_VERIFIED')
   test=once()
   if not test['pass']:raise RuntimeError('PREFLIGHT_'+test['error_class'])
   now=int(time.time())
   s={'started_at':now,'expires_at':now+7*86400,'attempts':1,'successes':1,'failures':0,
      'halt':None,'last':'PASS','last_update_count':test['updates'],
      'last_poll_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'last_offset':test['offset_after'],
      'proof':evidence,'last_error_class':None}
   write(STATE,s)
   try:changed=cron_update(True)
   except Exception:
    s['halt']='INSTALL_CRON_FAILED';write(STATE,s);raise
   emit(status='V29_GUARDED_AUTO_CALLBACK_SCHEDULED',every_minutes=1,
     expiry_days=7,preflight_updates=test['updates'],proof=evidence,
     cron_changed=changed,owner_exclusivity_proven=False,
     publication_enabled=False,channel_sends=0)
   return
  s=readstate()
  if not s:raise RuntimeError('V29_NOT_INSTALLED')
  if s.get('halt'):
   emit(status='V29_HALTED',reason=s['halt'],attempts=s['attempts']);return
  if time.time()>s['expires_at']:
   s['halt']='expired';write(STATE,s)
   cron_update(False)
   emit(status='V29_EXPIRED_CRON_REMOVED',attempts=s['attempts']);return
  s['attempts']+=1
  try:
   result=once()
  except subprocess.TimeoutExpired:
   result={'pass':False,'error_class':'ONE_SHOT_TIMEOUT'}
  except Exception:
   result={'pass':False,'error_class':'ONE_SHOT_UNEXPECTED_EXCEPTION'}
  if result['pass']:
   s['last']='PASS';s['successes']+=1;s['failures']=0
   s['last_update_count']=result['updates']
   s['last_offset']=result['offset_after']
   s['last_error_class']=None
  else:
   s['last']='FAILED';s['failures']+=1
   s['last_error_class']=result['error_class']
   if 'CONFLICT' in result['error_class'] or s['failures']>=3:
    s['halt']='poll_conflict_or_repeated_failures'
  s['last_poll_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  write(STATE,s)
  if s.get('halt'):cron_update(False)
  emit(status='V29_POLL_PASS' if result['pass'] else 'V29_POLL_FAILED',
       updates=result.get('updates'),outcomes=result.get('outcomes',[]),
       attempts=s['attempts'],consecutive_failures=s['failures'],
       halted=bool(s.get('halt')),error_class=s.get('last_error_class'),
       channel_sends=0)
 finally:os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='V29_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
       channel_sends=0);sys.exit(1)
