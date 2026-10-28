#!/usr/bin/env python3
"""NEWS RG hook installer for EXISTING rg_moderation.process_callback.

Never starts a new poller or enables public publication.
Fully backed up; no change on unknown module or failed selftest.
"""
import os,sys,json,pathlib,hashlib,subprocess,tempfile,ast,stat
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
TARGET=B/'rg_moderation.py'
MODULE=O/'news_rg_editorial_callbacks_v1.py'
SRC=pathlib.Path('/tmp/news_rg_editorial_callbacks_v1.py')
MARKER='# NEWS_RG_EDITORIAL_HOOK_V1'
HOOK='''    # NEWS_RG_EDITORIAL_HOOK_V1
    if str((update.get("callback_query") or {}).get("data","")).startswith("ne1:"):
        import importlib.util as _newsrg_util
        _newsrg_spec=_newsrg_util.spec_from_file_location("_newsrg_editorial_callbacks", "/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_editorial_callbacks_v1.py")
        _newsrg_mod=_newsrg_util.module_from_spec(_newsrg_spec)
        _newsrg_spec.loader.exec_module(_newsrg_mod)
        _newsrg_result=_newsrg_mod.process_callback(update,cfg)
        return _newsrg_result if _newsrg_result is not None else {"status":"EDITORIAL_CALLBACK_UNSUPPORTED"}
'''
def say(**x):print(json.dumps(x,ensure_ascii=False,sort_keys=True))
def stop(s):raise RuntimeError(s)
def atomic(p,b,mode):
 fd,n=tempfile.mkstemp(prefix='.newsrg_hook_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(n,p)
 finally:
  if os.path.exists(n):os.unlink(n)
def validate():
 if os.geteuid()!=0:stop('SUDO_REQUIRED')
 for p in (B,O):
  if not p.is_dir() or p.is_symlink():stop('UNSAFE_DIRECTORY')
 for p in (TARGET,SRC):
  if not p.is_file() or p.is_symlink():stop('UNSAFE_SOURCE_'+p.name)
 script=TARGET.read_text(encoding='utf-8')
 new=SRC.read_text(encoding='utf-8')
 if 'NEWS_RG_EDITORIAL_CALLBACK_SELFTEST_PASS' not in new or 'def process_callback(update,cfg):' not in new:
  stop('EDITORIAL_MODULE_UNRECOGNIZED')
 if script.count('def process_callback(update,cfg):')!=1:
  stop('EXISTING_BOT_CALLBACK_UNEXPECTED')
 if 'rg3:(approve|reject|recheck|similar)' not in script:
  stop('PRODUCTION_CALLBACK_CONTRACT_CHANGED')
 ast.parse(new)
 if MARKER in script:
  if MODULE.is_file():
   return {'status':'HOOK_ALREADY_INSTALLED','telegram_sends':0,'publications':0}
  stop('HOOK_PRESENT_MODULE_MISSING')
 check=subprocess.run(['/usr/bin/python3',str(SRC)],capture_output=True,text=True,timeout=15)
 if check.returncode or 'SELFTEST_PASS' not in check.stdout:stop('EDITORIAL_MODULE_SELFTEST_FAILED')
 head='def process_callback(update,cfg):\n'
 patched=script.replace(head,head+HOOK,1)
 ast.parse(patched)
 # py_compile preflight is syntax-only; no production module execution.
 for k in ('rg3:approve:','rg3:reject:','getUpdates'):
  if script.count(k)!=patched.count(k):stop('LEGACY_FLOW_CHANGED')
 return {'status':'READY_TO_INSTALL','existing_digest':hashlib.sha256(script.encode()).hexdigest()[:16],
         'patched':patched,'module':new,'telegram_sends':0,'publications':0}
def install():
 d=validate()
 if d['status']!='READY_TO_INSTALL':return d
 old=TARGET.read_bytes()
 original_mode=stat.S_IMODE(TARGET.stat().st_mode)
 backup=O/('rg_moderation.before_newsrg_hook_'+hashlib.sha256(old).hexdigest()[:16]+'.py')
 if backup.exists() and backup.is_symlink():stop('BACKUP_UNSAFE')
 if not backup.exists():atomic(backup,old,0o600)
 old_module=MODULE.read_bytes() if MODULE.exists() and MODULE.is_file() and not MODULE.is_symlink() else None
 if MODULE.is_symlink():stop('MODULE_SYMLINK')
 try:
  atomic(MODULE,d['module'].encode(),original_mode & 0o777)
  atomic(TARGET,d['patched'].encode(),original_mode)
  test=subprocess.run(['/usr/bin/python3','-m','py_compile',str(TARGET),str(MODULE)],capture_output=True,text=True,timeout=12)
  if test.returncode:stop('POST_INSTALL_SYNTAX_FAILED')
  t=subprocess.run(['/usr/bin/python3',str(MODULE)],capture_output=True,text=True,timeout=12)
  if t.returncode or 'SELFTEST_PASS' not in t.stdout:stop('POST_INSTALL_SELFTEST_FAILED')
 except Exception:
  atomic(TARGET,old,original_mode)
  if old_module is not None:atomic(MODULE,old_module,original_mode)
  elif MODULE.exists():MODULE.unlink()
  raise
 return {'status':'EDITORIAL_HOOK_INSTALLED','backup':str(backup),
   'callbacks':'ne1:accept / ne1:reject','legacy_bot_preserved':True,
   'second_poller':False,'publications':0,'telegram_sends':0,
   'note':'Only routes NEW editorial callbacks; old rg3 callback code unchanged'}
if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:
   ast.parse('def process_callback(update,cfg):\n    pass\n')
   say(status='INSTALLER_SELFTEST_PASS')
  elif mode==['preflight']:
   d=validate();d.pop('patched',None);d.pop('module',None);say(**d)
  elif mode==['install']:say(**install())
  else:stop('MODE_UNSUPPORTED')
 except Exception as e:
  say(status='SAFE_STOP',reason=str(e)[:120],telegram_sends=0,publications=0);sys.exit(2)
