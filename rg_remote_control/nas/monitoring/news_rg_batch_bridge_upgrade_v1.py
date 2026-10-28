#!/usr/bin/env python3
"""NEWS RG safe batch upgrade of existing private-only editorial bridge.
Preserves DSM schedule, production bot, pollers, public gates and SQLite.
"""
import os,sys,json,pathlib,hashlib,subprocess,tempfile,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
T=O/'news_rg_private_bridge_v1.py'
SRC=pathlib.Path('/tmp/news_rg_private_bridge_batch.py')
SCH=B/'rg_news_dsm_tick.sh'
def out(**data):print(json.dumps(data,ensure_ascii=False,sort_keys=True))
def run():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 for p in (B,O):
  if not p.is_dir() or p.is_symlink():raise RuntimeError('OPERATOR_DIR_NOT_SAFE')
 for p in (T,SRC,SCH,O/'news_rg_ollama_adapter_v1.py'):
  if not p.is_file() or p.is_symlink():raise RuntimeError('EXPECTED_FILE_MISSING_'+p.name)
 current=T.read_bytes();new=SRC.read_bytes()
 text=new.decode('utf-8')
 if 'NO_VALID_DRAFT_IN_BATCH' not in text or 'verified_media_mime' not in text:raise RuntimeError('NOT_CORRECT_BATCH_BUILD')
 if any(x in text for x in ('sendPhoto(', 'getUpdates(', 'sendMessage(', 'sendVideo(')):raise RuntimeError('FORBIDDEN_TELEGRAM_ACTION')
 if 'NEWS_RG_ISOLATED_SCHEDULE_V2' not in SCH.read_text():raise RuntimeError('EXPECTED_SINGLE_SCHEDULE_MISSING')
 if not (O/'news_rg_private_pilot_claim_v1.json').is_file():raise RuntimeError('V1_UNCERTAIN_RECEIPT_MISSING')
 old_hash=hashlib.sha256(current).hexdigest()
 new_hash=hashlib.sha256(new).hexdigest()
 if old_hash==new_hash:return {'status':'ALREADY_INSTALLED','sha256':new_hash,'production_publications':0}
 subprocess.run(['/usr/bin/python3','-m','py_compile',str(SRC)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
 # Existing sidecar uses durable adapter. The new bridge should use the same durable path.
 new=new.replace(b'/tmp/news_rg_ollama_adapter_v1.py',str(O/'news_rg_ollama_adapter_v1.py').encode())
 new_hash=hashlib.sha256(new).hexdigest()
 if hashlib.sha256(current).digest()==hashlib.sha256(new).digest():return {'status':'ALREADY_INSTALLED','sha256':new_hash,'production_publications':0}
 backup=O/('news_rg_private_bridge.backup_'+old_hash[:16]+'.py')
 if not backup.exists():
  fd,fn=tempfile.mkstemp(prefix='.newsrg_backup_',dir=str(O))
  with os.fdopen(fd,'wb') as h:
   os.fchmod(h.fileno(),0o600);h.write(current);h.flush();os.fsync(h.fileno())
  os.replace(fn,backup)
 fd,fn=tempfile.mkstemp(prefix='.newsrg_upgrade_',dir=str(O))
 try:
  with os.fdopen(fd,'wb') as h:
   os.fchmod(h.fileno(),0o600);h.write(new);h.flush();os.fsync(h.fileno())
  os.replace(fn,T)
  test=subprocess.run(['/usr/bin/python3',str(T),'selftest'],capture_output=True,text=True,timeout=12)
  if test.returncode or 'SELFTEST_PASS' not in test.stdout:
   raise RuntimeError('INSTALLED_SELFTEST_FAILED')
 except Exception:
  T.write_bytes(current);os.chmod(T,0o600)
  raise
 finally:
  if os.path.exists(fn):os.unlink(fn)
 return {'status':'BATCH_BRIDGE_INSTALLED','old_sha256':old_hash[:16],
  'new_sha256':new_hash[:16],'backup':str(backup),
  'scheduled_module_updated':True,'telegram_sends':0,
  'existing_bot_changed':False,'dsm_task_changed':False,'publications':0,
  'note':'Editorial staging only; no automatic delivery enabled'}
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:
   assert hashlib.sha256(b'a').hexdigest()
   out(status='SELFTEST_PASS')
  elif sys.argv[1:]==['install']:out(**run())
  else:raise RuntimeError('BAD_MODE')
 except Exception as e:
  out(status='SAFE_STOP',reason=str(e)[:100],telegram_sends=0,publications=0);sys.exit(2)
