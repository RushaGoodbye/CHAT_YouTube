#!/usr/bin/env python3
"""Upgrade only existing NEWS RG callback v29 expiry guard. No Telegram API calls."""
import os,sys,time,json,pathlib,ast,hashlib,stat,tempfile,subprocess
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
V=O/'callback_v29.py';S=O/'callback_v29_state.json';CR=pathlib.Path('/etc/crontab')
OLD="if time.time()>s['expires_at']:"
NEW="if not s.get('news_rg_continuous_guarded_v1',False) and time.time()>s['expires_at']:"
def emit(**kw):print(json.dumps(kw,sort_keys=True))
def put(p,b,mode):
 fd,tmp=tempfile.mkstemp(dir=str(p.parent),prefix='.news_rg_safe_')
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(p))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def check():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 for p in (V,S,CR):
  if not p.is_file() or p.is_symlink():raise RuntimeError('UNSAFE_'+p.name)
 source=V.read_text('utf-8');ast.parse(source)
 state=json.loads(S.read_text('utf-8'))
 if state.get('halt') or state.get('failures')!=0 or state.get('last_error_class') is not None:raise RuntimeError('CALLBACK_UNHEALTHY')
 if '# RG_NEWS2_CALLBACK_PROBATION_V29' not in source or 'RG_NEWS2_CALLBACK_PROBATION_V29' not in CR.read_text('utf-8'):raise RuntimeError('CURRENT_CRON_NOT_RECOGNIZED')
 if 'FOREIGN_CALLBACK_FAMILY' not in source or 'CONFLICT' not in source or 'cron_update(False)' not in source:raise RuntimeError('SAFETY_GUARDS_UNVERIFIED')
 if state.get('news_rg_continuous_guarded_v1') is True and NEW in source:return source,state,True
 if source.count(OLD)!=1 or 'news_rg_continuous_guarded_v1' in source:raise RuntimeError('PATCH_ANCHOR_MISMATCH')
 if time.time()>=state.get('expires_at',0):raise RuntimeError('EXPIRED_ALREADY')
 return source,state,False
def install():
 source,state,done=check()
 if done:return emit(status='ALREADY_CONTINUOUS')
 ps=subprocess.check_output(['ps','-eo','args']).decode('utf-8','replace')
 for line in ps.splitlines():
  if ('callback_v29.py' in line or 'rg_news2_p31_guarded_callback_once.py' in line) and 'python' in line and 'news_rg_callback_continuous_upgrade' not in line:raise RuntimeError('CALLBACK_BUSY')
 old_v=V.read_bytes();old_s=S.read_bytes();digest=hashlib.sha256(old_v+old_s).hexdigest()[:16]
 for p,b in ((O/('callback_v29.before_continuous_'+digest+'.py'),old_v),(O/('callback_v29_state.before_continuous_'+digest+'.json'),old_s)):
  fd=os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
 new=source.replace(OLD,NEW+' # NEWS_RG_CONTINUOUS_V1',1);ast.parse(new)
 state['news_rg_continuous_guarded_v1']=True
 mode_v=stat.S_IMODE(V.stat().st_mode);mode_s=stat.S_IMODE(S.stat().st_mode)
 try:
  if V.read_bytes()!=old_v or S.read_bytes()!=old_s:raise RuntimeError('CONCURRENT_CHANGE')
  put(V,new.encode('utf-8'),mode_v);put(S,json.dumps(state,sort_keys=True).encode('utf-8'),mode_s)
  ast.parse(V.read_text('utf-8'))
  if not json.loads(S.read_text('utf-8')).get('news_rg_continuous_guarded_v1'):raise RuntimeError('VERIFY_FAILED')
 except Exception:
  put(V,old_v,mode_v);put(S,old_s,mode_s);raise
 emit(status='CALLBACK_CONTINUOUS_INSTALLED',offset_unchanged=True,cron_unchanged=True,new_pollers=0,telegram_calls=0,publications=0,conflict_guard_preserved=True)
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:
   ast.parse('def x(s):\n '+NEW+'\n  pass\n')
   print('NEWS_RG_CALLBACK_CONTINUOUS_SELFTEST_PASS')
  elif sys.argv[1:]==['preflight']:
   _,_,done=check();emit(status='ALREADY_CONTINUOUS' if done else 'PREFLIGHT_PASS',telegram_calls=0)
  elif sys.argv[1:]==['install']:install()
  else:raise RuntimeError('EXPECTED_SELFTEST_PREFLIGHT_INSTALL')
 except Exception as e:
  emit(status='SAFE_STOP',reason=str(e)[:180],telegram_calls=0,publications=0);sys.exit(2)
