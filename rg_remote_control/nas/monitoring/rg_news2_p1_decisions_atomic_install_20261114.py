#!/usr/bin/env python3
"""NEWS2 P1 exact pinned decision-schema upgrade.

Only replaces TWO read-only diagnostic modules; no bot, worker, scheduler,
moderation decision, public/private receipt or Telegram API changed.
Backs up exact old SHA256 files, atomic replace under root lock, real ledger
post-deploy QA, auto rollback on any failure, explicit rollback supported.
"""
import datetime,fcntl,hashlib,json,os,stat,subprocess,sys,tempfile
from pathlib import Path

O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
TARGETS={
 'rg_news2_privileged_readonly_gateway_v1.py':{
  'old_sha256':'b9ccab1de64a80a62f181a9d8a683db712e17aa1cd89647bb4d20d031436915f',
  'new_git_blob':'35adf9e32c078c17bc8ad63301ed78df940d7674',
  'stage':Path('/tmp/rg_news2_privileged_readonly_gateway_v2.py'),
  'mode':'audit',
  'selftest':'NEWS2_PRIVILEGED_READONLY_GATEWAY_SELFTEST_PASS'},
 'rg_news2_decisions_reconcile_readonly_v1.py':{
  'old_sha256':'debc2f9ab30bee510c7002668c551be3e913320a775f7d24a1e03db876648592',
  'new_git_blob':'2cc4044606cf6c4f91de1fd35a7cefb820e651e4',
  'stage':Path('/tmp/rg_news2_decisions_reconcile_readonly_v2.py'),
  'mode':'inspect',
  'selftest':'NEWS2_DECISION_RECONCILIATION_SELFTEST_PASS'},
}
BK=O/'rg_news2_release_backups_v5'
REL=BK/'p1_decision_schema_20261114'
RECEIPT=REL/'receipt.json'
LOCK=O/'rg_news2_p1_schema_release.lock'
class Stop(ValueError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def safe(p,limit=160000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or st.st_size<=0 or st.st_size>limit:
  raise Stop('UNSAFE_SOURCE_'+p.name)
 return p.read_bytes()
def rootdir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 st=p.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
  raise Stop('UNSAFE_DIRECTORY_'+p.name)
def atomic(p,data,mode=0o600):
 fd,tmp=tempfile.mkstemp(prefix='.rg_news2_p1_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def process(args,timeout=55):
 r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if r.returncode:raise Stop('TEST_COMMAND_FAILED_'+Path(args[1]).name)
 return r.stdout
def verified_sources():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 rootdir(O)
 if LOCK.is_symlink() or BK.is_symlink() or REL.is_symlink() or RECEIPT.is_symlink():
  raise Stop('UNSAFE_RELEASE_SYMLINK')
 if REL.exists():raise Stop('RELEASE_ALREADY_EXISTS')
 inputs={}
 for name,info in TARGETS.items():
  target=O/name
  old=safe(target)
  if target.lstat().st_uid!=0 or sha(old)!=info['old_sha256']:
   raise Stop('LIVE_VERSION_DRIFT_'+name)
  new=safe(info['stage'])
  if blob(new)!=info['new_git_blob']:
   raise Stop('STAGING_PIN_MISMATCH_'+name)
  if info['stage'].is_symlink():raise Stop('STAGED_SYMLINK_'+name)
  compile(new,str(info['stage']),'exec')
  if info['selftest'] not in process(['/usr/bin/python3',str(info['stage']),'selftest']):
   raise Stop('STAGING_SELFTEST_FAILED_'+name)
  inputs[name]=(old,new,stat.S_IMODE(target.stat().st_mode))
 return inputs

def audit_outputs():
 gateway=json.loads(process(['/usr/bin/python3',str(O/'rg_news2_privileged_readonly_gateway_v1.py'),'audit']))
 rec=json.loads(process(['/usr/bin/python3',str(O/'rg_news2_decisions_reconcile_readonly_v1.py'),'inspect']))
 ds=gateway.get('decision_receipts') or {}
 counts=ds.get('counts') or {}
 expected={'editorially_accepted_not_published':48,'editorially_rejected':198,'editorially_expired':1}
 if counts!=expected or ds.get('automatically_rejected_expired_v2')!=26 or ds.get('parse_errors')!=0:
  raise Stop('LIVE_GATEWAY_DECISION_COUNTS_NOT_EXPECTED')
 if rec.get('decision_counts')!=expected or rec.get('automatically_rejected_expired_v2')!=26 or rec.get('decision_parse_issues')!={}:
  raise Stop('LIVE_RECONCILER_DECISION_COUNTS_NOT_EXPECTED')
 match=rec.get('accepted_publication_reconciliation') or {}
 if match.get('accepted_with_public_receipt_PUBLIC_PUBLISHED_CONFIRMED')!=47 or match.get('accepted_without_public_receipt_before_activation_not_publishable')!=1:
  raise Stop('LIVE_HISTORY_OR_PUBLICATION_MISMATCH')
 if gateway.get('read_only') is not True or rec.get('read_only') is not True or rec.get('telegram_calls')!=0 or rec.get('production_writes')!=0:
  raise Stop('READONLY_QA_UNPROVEN')
 return {'decisions':counts,'automatic_rejected':26,'real_confirmed_publications':47,
     'pre_activation_nonpublishable':1,'parse_errors':0,'telegram_calls':0,'publications':0}

def mutex():
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
 fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 return fd
def apply():
 inputs=verified_sources()
 fd=mutex()
 try:
  inputs=verified_sources()
  rootdir(BK,create=True);rootdir(REL,create=True)
  for name,(old,new,mode) in inputs.items():
   atomic(REL/('before_'+name),old,0o600)
   if sha(safe(REL/('before_'+name)))!=TARGETS[name]['old_sha256']:
    raise Stop('BACKUP_VERIFY_FAILED_'+name)
  attempted=[]
  try:
   for name,(old,new,mode) in inputs.items():
    attempted.append(name)
    atomic(O/name,new,mode)
    if blob(safe(O/name))!=TARGETS[name]['new_git_blob']:
     raise Stop('INSTALL_CHECKSUM_FAILED_'+name)
   qa=audit_outputs()
   rec={'status':'APPLIED_QA_PASS','release':'NEWS2_P1_DECISIONS_SCHEMA_20261114',
       'applied_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'backup_verified':True,'scripts_updated':sorted(TARGETS),'qa':qa,
       'telegram_calls':0,'production_publications':0}
   atomic(RECEIPT,(json.dumps(rec,sort_keys=True)+'\n').encode('utf8'))
   return rec
  except Exception:
   for name in reversed(attempted):
    old,new,mode=inputs[name]
    atomic(O/name,old,mode)
    if sha(safe(O/name))!=TARGETS[name]['old_sha256']:
     raise Stop('ROLLBACK_SHA_MISMATCH_'+name)
   raise
 finally:os.close(fd)

def rollback():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 rootdir(BK);rootdir(REL)
 receipt=json.loads(safe(RECEIPT))
 if receipt.get('status')!='APPLIED_QA_PASS':raise Stop('RELEASE_NOT_APPLIED')
 fd=mutex()
 try:
  for name,info in TARGETS.items():
   if blob(safe(O/name))!=info['new_git_blob']:
    raise Stop('TARGET_CHANGED_'+name)
  for name,info in TARGETS.items():
   orig=safe(REL/('before_'+name))
   if sha(orig)!=info['old_sha256']:raise Stop('BACKUP_DRIFT_'+name)
   atomic(O/name,orig,stat.S_IMODE((O/name).stat().st_mode))
  if any(sha(safe(O/name))!=info['old_sha256'] for name,info in TARGETS.items()):
   raise Stop('ROLLBACK_VERIFY_FAILED')
  return {'status':'ROLLBACK_VERIFIED','telegram_calls':0,'publications':0}
 finally:os.close(fd)
def selftest():
 assert len(TARGETS)==2
 assert all(len(i['old_sha256'])==64 and len(i['new_git_blob'])==40 for i in TARGETS.values())
 assert not REL.is_relative_to(Path('/tmp'))
 print('NEWS2_P1_DECISIONS_ATOMIC_INSTALLER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  a=sys.argv[1:]
  if a==['selftest']:selftest()
  elif a==['preflight']:
   files=verified_sources()
   print(json.dumps({'status':'PREFLIGHT_PASS','sources':len(files),'publications':0,'telegram_calls':0}))
  elif a==['apply']:print(json.dumps(apply(),sort_keys=True))
  elif a==['rollback']:print(json.dumps(rollback(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_ACTION')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:140],'publications':0,'telegram_calls':0}))
  raise SystemExit(2)
