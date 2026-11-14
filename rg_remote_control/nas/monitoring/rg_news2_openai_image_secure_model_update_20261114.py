#!/usr/bin/env python3
"""NEWS2 safely update GPT image model and key storage, never call API.

Updates generator and existing NAS scheduler atomically under existing locks.
Pins old SHA256, creates independently verified backups, and checks current
stable pin of 18 modules is unchanged. NO live Telegram or image API calls.
"""
import datetime,fcntl,hashlib,json,os,stat,subprocess,sys,tempfile
from pathlib import Path
BASE=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
GEN=OP/'rg_news2_chatgpt_image_illustration_v1.py'
TICK=BASE/'rg_news_dsm_tick.sh'
PIN=OP/'news_rg_stability_releases_v1/pinned_release_v1.json'
REL=OP/'rg_news2_release_backups_v9/openai_image_secure_model_20261114'
BACK_GEN=REL/'generator.before.py'
BACK_TICK=REL/'dsm_tick.before.sh'
RECEIPT=REL/'receipt.json'
LOCKS=(OP/'news_rg_ai_illustration_v1.lock',
       OP/'news_rg_dispatch_schedule.lock',
       OP/'news_rg_stability_releases_v1/release.lock')
OLD_GEN_SHA='37f55ef414174219c1a4e01745baab463b10b1ff51401e9f1597806925809de2'
OLD_TICK_SHA='f7459af39c2b42b86890443586930bfdc63c4036537c8960244a230c7024d41d'
OLD_KEY='/volume1/docker/RG_SECRETS/rg_news_openai_image_api_key'
NEW_KEY='/volume1/docker/RG_TELEGRAM_NEWS_2/operator/.secrets/openai_image_api_key'
OLD_MODEL="MODEL='chatgpt-image-latest'"
NEW_MODEL="MODEL='gpt-image-2'"
class Stop(ValueError):pass
def sha(x):return hashlib.sha256(x).hexdigest()
def regular(p,lim=200000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or not 50<st.st_size<lim:
  raise Stop('UNSAFE_ROOT_FILE_'+p.name)
 return p.read_bytes()
def rootdir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 st=p.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077:
  raise Stop('UNSAFE_ROOT_DIRECTORY_'+p.name)
def patch_one(s,old,new,label):
 if s.count(old)!=1:raise Stop('CODE_CHANGED_'+label)
 return s.replace(old,new,1)
def candidates():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 rootdir(OP);rootdir(OP/'news_rg_stability_releases_v1')
 if REL.exists() or REL.is_symlink():raise Stop('RELEASE_ALREADY_USED')
 before_gen=regular(GEN);before_tick=regular(TICK)
 if sha(before_gen)!=OLD_GEN_SHA or sha(before_tick)!=OLD_TICK_SHA:
  raise Stop('SOURCE_DRIFT_NO_CHANGES')
 pin=json.loads(regular(PIN,100000))
 if pin.get('version')!='2026-11-14-stable5.4-visual-only-moderation' or len(pin.get('files',{}))!=18:
  raise Stop('PINNED_GUARD_NOT_EXPECTED')
 s=before_gen.decode('utf8')
 s=patch_one(s,"SECRET=pathlib.Path('"+OLD_KEY+"')",
                "SECRET=pathlib.Path('"+NEW_KEY+"')",'secret_path')
 s=patch_one(s,OLD_MODEL,NEW_MODEL,'image_model')
 s=patch_one(s,"assert MODEL=='chatgpt-image-latest'",
                  "assert MODEL=='gpt-image-2'",'selftest')
 sh=patch_one(before_tick.decode('utf8'),OLD_KEY,NEW_KEY,'schedule_secret')
 a=s.encode('utf8');b=sh.encode('utf8')
 compile(a,'new_image_script.py','exec')
 # zero API calls; only pure selftest.
 with tempfile.TemporaryDirectory(prefix='rg_ai_model_') as td:
  file=Path(td)/'image_candidate.py';file.write_bytes(a)
  result=subprocess.run(['/usr/bin/python3',str(file),'selftest'],
      capture_output=True,text=True,timeout=15)
  if result.returncode or 'NEWS2_GPT_IMAGE_ILLUSTRATION_SELFTEST_PASS' not in result.stdout:
   raise Stop('CANDIDATE_SELFTEST_FAILED')
  target=Path(td)/'schedule_candidate.sh';target.write_bytes(b)
  chk=subprocess.run(['/bin/sh','-n',str(target)],capture_output=True,timeout=12)
  if chk.returncode:raise Stop('CANDIDATE_SHELL_INVALID')
 if b.count(b'rg_news2_chatgpt_image_illustration_v1.py')!=1:
  raise Stop('SCHEDULE_DUPLICATE')
 return before_gen,before_tick,a,b
def atomic(p,data,mode=0o600):
 fd,tmp=tempfile.mkstemp(prefix='.rg_secure_image_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def hold():
 fds=[]
 try:
  for p in LOCKS:
   if p.is_symlink():raise Stop('LOCK_SYMLINK')
   fd=os.open(str(p),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except Exception:os.close(fd);raise
   fds.append(fd)
  return fds
 except Exception:
  for fd in reversed(fds):os.close(fd)
  raise Stop('GUARD_OR_GENERATOR_BUSY')
def apply():
 fds=hold()
 try:
  original,old_tick,new_gen,new_tick=candidates()
  rootdir(OP/'rg_news2_release_backups_v9',create=True)
  rootdir(REL,create=True)
  atomic(BACK_GEN,original);atomic(BACK_TICK,old_tick)
  if sha(regular(BACK_GEN))!=OLD_GEN_SHA or sha(regular(BACK_TICK))!=OLD_TICK_SHA:
   raise Stop('BACKUP_INVALID')
  installed=False
  try:
   atomic(GEN,new_gen,stat.S_IMODE(GEN.stat().st_mode));installed=True
   atomic(TICK,new_tick,stat.S_IMODE(TICK.stat().st_mode))
   if sha(regular(GEN))!=sha(new_gen) or sha(regular(TICK))!=sha(new_tick):
    raise Stop('POSTINSTALL_HASH_INVALID')
   s=OP/'.secrets'
   rootdir(s,create=True)
   receipt={'status':'APPLIED_QA_PASS','release':'NEWS2_OPENAI_IMAGE_SECURE_MODEL_V2',
     'model':'gpt-image-2','key_path':NEW_KEY,'key_present':(s/'openai_image_api_key').exists(),
     'generator_sha256':sha(new_gen),'dsm_sha256':sha(new_tick),
     'backup_verified':True,'telegram_calls':0,'image_api_calls':0,'publications':0,
     'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
   atomic(RECEIPT,(json.dumps(receipt,sort_keys=True)+'\n').encode('utf8'))
   return receipt
  except Exception:
   if installed:
    atomic(GEN,original,stat.S_IMODE(GEN.stat().st_mode))
    atomic(TICK,old_tick,stat.S_IMODE(TICK.stat().st_mode))
    if sha(regular(GEN))!=OLD_GEN_SHA or sha(regular(TICK))!=OLD_TICK_SHA:
     raise Stop('ROLLBACK_UNVERIFIED')
   raise
 finally:
  for fd in reversed(fds):os.close(fd)
def selftest():
 assert len(OLD_TICK_SHA)==len(OLD_GEN_SHA)==64
 assert NEW_KEY.startswith(str(OP)) and OLD_KEY!=NEW_KEY
 assert NEW_MODEL=="MODEL='gpt-image-2'"
 print('NEWS2_SECURE_IMAGE_MODEL_INSTALLER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  a=sys.argv[1:]
  if a==['selftest']:selftest()
  elif a==['preflight']:
   old,shell,new,sh=candidates()
   print(json.dumps({'status':'PREFLIGHT_PASS','new_generator_sha256':sha(new),'new_dsm_sha256':sha(sh),
                      'telegram_calls':0,'image_api_calls':0,'publications':0}))
  elif a==['apply']:print(json.dumps(apply(),sort_keys=True))
  else:raise Stop('UNKNOWN_ACTION')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:155],
                   'telegram_calls':0,'image_api_calls':0,'publications':0}))
  raise SystemExit(2)
