#!/usr/bin/env python3
"""NEWS2 install dormant, key-gated GPT Image illustrator on existing DSM tick.

No key, no generation, no API call and no Telegram sends at installation.
Once an authorized OpenAI API key is securely configured in the root-only
secret file, the old 10-minute DSM scheduler calls this stage before private
review dispatch. The separate sender blocks text-only cards regardless.
"""
import datetime,fcntl,hashlib,json,os,stat,subprocess,sys,tempfile
from pathlib import Path

B=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
TICK=B/'rg_news_dsm_tick.sh'
TARGET=O/'rg_news2_chatgpt_image_illustration_v1.py'
STAGED=Path('/tmp/rg_news2_chatgpt_image_illustration_v1.py')
BACK=O/'rg_news2_release_backups_v8/image_generator_20261114'
OLD_SH='46d1403bf52de42fdcff8a5991286b6a21e2a913a7ed1c419efa9b1caa18a339'
OLD_BLOB='4f7731dc1b6ff61d49afcb8ff40fbc47724e0bcb'
ANCHOR='# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1'
LINE="""# NEWS_RG_GPT_IMAGE_ILLUSTRATION_V1
# No AI charges unless root-only API key exists; max 3 AI illustrations/day.
if [ -s '/volume1/docker/RG_SECRETS/rg_news_openai_image_api_key' ]; then
  "$RG_NEWS_PYTHON" '/volume1/docker/RG_TELEGRAM_NEWS_2/operator/rg_news2_chatgpt_image_illustration_v1.py' tick >> '/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_stability_releases_v1/ai_image_schedule.log' 2>&1 || :
fi
"""
class Stop(ValueError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def safe(p,limit=170000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or not 1<=st.st_size<=limit or st.st_uid!=0:
  raise Stop('UNSAFE_FILE_'+p.name)
 return p.read_bytes()
def atomic(p,b,mode):
 fd,t=tempfile.mkstemp(prefix='.rg_ai_image_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(t,p)
 finally:
  if os.path.exists(t):os.unlink(t)
def preflight():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 if BACK.exists() or TARGET.exists() or BACK.is_symlink():
  raise Stop('AI_GENERATOR_ALREADY_INSTALLED')
 shell=safe(TICK)
 if sha(shell)!=OLD_SH:raise Stop('DSM_SOURCE_HASH_CHANGED')
 text=shell.decode('utf8')
 if text.count(ANCHOR)!=1 or 'rg_news2_chatgpt_image_illustration_v1.py' in text:
  raise Stop('DSM_INSERTION_NOT_UNIQUE')
 script=STAGED.read_bytes()
 if STAGED.is_symlink() or blob(script)!=OLD_BLOB:
  raise Stop('STAGED_GENERATOR_PIN_CHANGED')
 compile(script,str(STAGED),'exec')
 py=O/'tools/python-3.15.2/bin/python3.15'
 cp=subprocess.run([str(py),str(STAGED),'selftest'],capture_output=True,text=True,timeout=30)
 if cp.returncode or 'NEWS2_GPT_IMAGE_ILLUSTRATION_SELFTEST_PASS' not in cp.stdout:
  raise Stop('IMAGE_SELFTEST_FAILED')
 new=text.replace(ANCHOR,LINE+ANCHOR,1).encode('utf8')
 if new.count(b'rg_news2_chatgpt_image_illustration_v1.py')!=1:
  raise Stop('DUPLICATE_GENERATION_HOOK')
 with tempfile.TemporaryDirectory(prefix='rg_ai_hook_') as t:
  tmp=Path(t)/'tick.sh';tmp.write_bytes(new)
  res=subprocess.run(['/bin/sh','-n',str(tmp)],capture_output=True,timeout=15)
  if res.returncode:raise Stop('DSM_SHELL_SYNTAX_INVALID')
 return shell,script,new
def apply():
 old,script,new=preflight()
 BACK.mkdir(mode=0o700,parents=True)
 atomic(BACK/'tick_before.sh',old,0o600)
 if sha(safe(BACK/'tick_before.sh'))!=OLD_SH:raise Stop('BACKUP_VERIFICATION_FAILED')
 mode=stat.S_IMODE(TICK.stat().st_mode)
 inserted=False
 try:
  atomic(TARGET,script,0o700);inserted=True
  atomic(TICK,new,mode)
  if sha(safe(TICK))!=sha(new) or blob(safe(TARGET))!=OLD_BLOB:
   raise Stop('INSTALLED_HASH_MISMATCH')
  receipt={'status':'APPLIED_QA_PASS_KEY_GATED','release':'NEWS2_GPT_IMAGE_ILLUSTRATION_HOOK_20261114',
   'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'new_dsm_sha256':sha(new),'generator_git_blob':OLD_BLOB,
   'api_key_configured':Path('/volume1/docker/RG_SECRETS/rg_news_openai_image_api_key').is_file(),
   'key_required_before_generation':True,'max_daily_generations':3,
   'backup_verified':True,'openai_calls_during_install':0,'telegram_calls':0,'publications':0}
  atomic(BACK/'receipt.json',(json.dumps(receipt,sort_keys=True)+'\n').encode('utf8'),0o600)
  return receipt
 except Exception:
  atomic(TICK,old,mode)
  if inserted and TARGET.is_file():TARGET.unlink()
  if sha(safe(TICK))!=OLD_SH:raise Stop('ROLLBACK_FAILED')
  raise
def selftest():
 assert len(OLD_SH)==64 and ANCHOR in LINE+ANCHOR
 assert "if [ -s " in LINE and LINE.count('rg_news2_chatgpt_image_illustration_v1.py')==1
 print('NEWS2_GPT_IMAGE_SCHEDULE_INSTALLER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  a=sys.argv[1:]
  if a==['selftest']:selftest()
  elif a==['preflight']:
   old,script,new=preflight()
   print(json.dumps({'status':'PREFLIGHT_PASS','new_dsm_sha256':sha(new),
    'new_generator_git_blob':blob(script),'image_api_calls':0,'telegram_calls':0}))
  elif a==['apply']:print(json.dumps(apply(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:170],
   'image_api_calls':0,'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
