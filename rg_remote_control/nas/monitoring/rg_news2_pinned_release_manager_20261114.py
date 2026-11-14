#!/usr/bin/env python3
"""Pinned NEWS2 release 20261114: only read-only diagnostic gateway.
No arbitrary file paths, remote code, Telegram calls, daemon restarts or sends.
"""
import datetime,fcntl,hashlib,json,os,stat,subprocess,sys,tempfile
from pathlib import Path
OP=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
DST=OP/'rg_news2_privileged_readonly_gateway_v1.py'
SRC=Path('/tmp/rg_news2_privileged_readonly_gateway_v1.py')
TEST=Path('/tmp/rg_news2_privileged_audit_decision_test_v1.py')
BK=OP/'rg_news2_release_backups_v1'
REL=BK/'decision_gateway_20261114_v1'
OLD=REL/'gateway_before.py'
RECEIPT=REL/'release_receipt.json'
LOCK=OP/'rg_news2_release_manager_v1.lock'
PREV='c3818f5a7634f1d6d2e6987a456c67e3b42fb115'
NEW='c2da7f1d6fbefc739dbb10151050857a2dccb3e5'
TEST_SHA='b17751848c0a91d34f44ed3150b89e749ccdfcde'
class Stop(ValueError):pass
def blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def regular(p,sha=None):
 s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_size<1 or s.st_size>100000 or s.st_mode&0o022:raise Stop('UNSAFE_FILE_'+p.name)
 b=p.read_bytes()
 if sha and blob(b)!=sha:raise Stop('PINNED_HASH_MISMATCH_'+p.name)
 return b
def rootdir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise Stop('UNSAFE_DIRECTORY_'+p.name)
def atomic(p,data,mode):
 fd,tmp=tempfile.mkstemp(prefix='.news2_release_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def execute(cmd):
 p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=45)
 if p.returncode:raise Stop('TEST_FAILED_'+cmd[-1].replace('/','_')[-45:])
 return p.stdout
def preflight():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 rootdir(OP)
 current=regular(DST)
 if DST.lstat().st_uid!=0 or blob(current) not in (PREV,NEW):raise Stop('LIVE_VERSION_DRIFT')
 new=regular(SRC,NEW)
 regular(TEST,TEST_SHA)
 if 'NEWS2_PRIVILEGED_READONLY_GATEWAY_SELFTEST_PASS' not in execute(['/usr/bin/python3',str(SRC),'selftest']):raise Stop('SELFTEST_MISSING')
 if 'NEWS2_DECISION_GATEWAY_ISOLATED_REGRESSION_PASS' not in execute(['/usr/bin/python3',str(TEST)]):raise Stop('REGRESSION_MISSING')
 for p in (LOCK,BK,REL,OLD,RECEIPT):
  if p.is_symlink():raise Stop('SYMLINK_'+p.name)
 return current,new
def evidence():
 txt=execute(['/usr/bin/python3',str(DST),'audit'])
 try:r=json.loads(txt)
 except ValueError:raise Stop('AUDIT_INVALID_JSON')
 if not r.get('read_only') or r.get('telegram_api_calls')!=0 or r.get('production_writes')!=0:raise Stop('AUDIT_SIDE_EFFECTS')
 dec=r.get('decision_receipts') or {}
 c=dec.get('counts') or {}
 if not dec.get('present') or sum(c.values())<200 or dec.get('parse_errors',999)>5:raise Stop('DECISION_QA_FAIL')
 if 'editorially_accepted_not_published' not in c or 'editorially_rejected' not in c:raise Stop('DECISION_ENUM_MISSING')
 return {'decision_counts':c,'decision_issues':dec.get('issues',{}),'parse_errors':dec['parse_errors'],
         'private_sent':((r.get('private_receipts') or {}).get('counts') or {}).get('PRIVATE_SENT_CONFIRMED'),
         'public_sent':((r.get('public_receipts') or {}).get('counts') or {}).get('PUBLIC_PUBLISHED_CONFIRMED')}
def mutex():
 if LOCK.is_symlink():raise Stop('LOCK_SYMLINK')
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
 fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 return fd
def apply():
 old,new=preflight()
 if blob(old)==NEW:return {'status':'ALREADY_INSTALLED','qa':evidence()}
 fd=mutex()
 try:
  if blob(regular(DST))!=PREV:raise Stop('CHANGED_BEFORE_LOCK')
  rootdir(BK,True);rootdir(REL,True)
  if OLD.exists() or RECEIPT.exists():raise Stop('BACKUP_EXISTS_SAFE_STOP')
  atomic(OLD,old,0o600);regular(OLD,PREV)
  try:
   atomic(DST,new,0o700);regular(DST,NEW)
   qa=evidence()
   rec={'status':'APPLIED_QA_PASS','before':PREV,'after':NEW,
     'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'qa':qa}
   atomic(RECEIPT,(json.dumps(rec,sort_keys=True)+'\n').encode(),0o600)
   return {'status':'APPLIED_QA_PASS','qa':qa,'backup_verified':True}
  except Exception:
   atomic(DST,old,0o700);regular(DST,PREV)
   raise
 finally:os.close(fd)
def rollback():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 rootdir(OP);rootdir(BK);rootdir(REL)
 old=regular(OLD,PREV)
 current=regular(DST,NEW)
 rec=json.loads(regular(RECEIPT))
 if rec.get('status')!='APPLIED_QA_PASS' or rec.get('after')!=NEW:raise Stop('RECEIPT_MISMATCH')
 fd=mutex()
 try:
  if blob(regular(DST))!=NEW:raise Stop('TARGET_DRIFT')
  atomic(DST,old,0o700);regular(DST,PREV)
  return {'status':'ROLLBACK_VERIFIED'}
 finally:os.close(fd)
def test():
 assert PREV!=NEW and len(PREV)==len(NEW)==40
 assert DST.parent==OP and SRC.parent==Path('/tmp')
 print('RG_NEWS2_PINNED_RELEASE_MANAGER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:test()
  elif sys.argv[1:]==['preflight']:
   old,_=preflight();print(json.dumps({'status':'PREFLIGHT_PASS','target_version':'OLD' if blob(old)==PREV else 'NEW'}))
  elif sys.argv[1:]==['apply']:print(json.dumps(apply(),sort_keys=True))
  elif sys.argv[1:]==['rollback']:print(json.dumps(rollback(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_ACTION')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100],'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
