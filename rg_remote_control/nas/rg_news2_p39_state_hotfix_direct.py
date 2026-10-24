#!/usr/bin/env python3
"""P39: guarded moderation-state fix for RG Telegram News 2.0 on NAS.
Only modifies rg_moderation.py after syntax and SQLite shadow checks.
No Telegram calls, no cron changes, no channel publication.
"""
import ast,datetime,fcntl,json,os,pathlib,sqlite3,stat,sys,tempfile
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
SOURCE=BASE/'rg_moderation.py'
DB=BASE/'news.sqlite3'
OLD="if item['status']!='awaiting_moderation' or item['photo_reviewed']!=1:"
NEW=("if decision=='approve':return {'status':'APPROVAL_DISABLED_UNTIL_CUTOVER'}\n"
     "        if item['status'] not in ('awaiting_moderation','awaiting_photo_review'):")
SQL_OLD="status='awaiting_moderation' AND photo_reviewed=1"
SQL_NEW="status IN ('awaiting_moderation','awaiting_photo_review')"
def output(**d):print(json.dumps(d,ensure_ascii=False,sort_keys=True),flush=True)
def fail(msg):raise RuntimeError(msg)
def checks():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 if not OP.is_dir() or OP.is_symlink() or not SOURCE.is_file() or SOURCE.is_symlink():fail('INVALID_SOURCE')
 if not DB.is_file() or DB.is_symlink():fail('INVALID_DB')
 if (pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')).exists():fail('LEGACY_GATE_PRESENT')
 if (BASE/'PUBLISH_ENABLED').exists() or (BASE/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():fail('PUBLICATION_OR_OWNER_FLAG_OPEN')
 if not (BASE/'MODERATION_DELIVERY_ENABLED').is_file():fail('MODERATION_DISABLED')
 cron=pathlib.Path('/etc/crontab').read_text()
 if sum('RG_NEWS2_CALLBACK_PROBATION_V29' in s and not s.lstrip().startswith('#') for s in cron.splitlines())!=1:fail('EXPECTED_CRON_MISSING')
def patch(text):
 tree=ast.parse(text)
 funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='process_callback']
 if len(funcs)!=1:fail('HANDLER_CHANGED')
 n=funcs[0];lines=text.splitlines(keepends=True)
 body=''.join(lines[n.lineno-1:n.end_lineno])
 if NEW in body and SQL_NEW in body and OLD not in body and SQL_OLD not in body:return text,False
 if body.count(OLD)!=1 or body.count(SQL_OLD)!=1:fail('STATE_MATCH_DRIFT')
 if "decision" not in body or "'approve':'approved_for_publication'" not in body:fail('ACTION_MAPPING_CHANGED')
 revised=body.replace(OLD,NEW,1).replace(SQL_OLD,SQL_NEW,1)
 final=''.join(lines[:n.lineno-1])+revised+''.join(lines[n.end_lineno:])
 compile(final,str(SOURCE),'exec')
 return final,True
def shadow_check():
 with tempfile.TemporaryDirectory(prefix='news2_p39_') as d:
  path=pathlib.Path(d)/'shadow.sqlite3'
  with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True,timeout=10) as live:
   with sqlite3.connect(str(path)) as dest:live.backup(dest)
  with sqlite3.connect(str(path)) as test:
   row=test.execute("""SELECT c.id,c.status FROM candidates c
     JOIN moderation_dispatch m ON m.candidate_id=c.id
     WHERE c.status='awaiting_photo_review' LIMIT 1""").fetchone()
   if not row:fail('NO_REAL_AWAITING_PHOTO_REVIEW_CARD')
   cid,status=row
   if status!='awaiting_photo_review':fail('SHADOW_STATE_UNEXPECTED')
   result=test.execute("UPDATE candidates SET status='needs_recheck' WHERE id=? AND "+SQL_NEW,(cid,))
   if result.rowcount!=1:fail('RECHECK_SHADOW_UPDATE_NOT_MATCHED')
   newstatus=test.execute("SELECT status FROM candidates WHERE id=?",(cid,)).fetchone()[0]
   if newstatus!='needs_recheck':fail('RECHECK_SHADOW_STATE_MISMATCH')
  return 'PHOTO_REVIEW_DB_TRANSITION_PASS'
def lock(name):
 fd=os.open(str(OP/name),os.O_CREAT|os.O_RDWR,0o600)
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except (OSError,BlockingIOError):
  os.close(fd);fail('CALLBACK_RUNNING_RETRY')
 return fd
def apply(text,changed):
 if not changed:return {'already_installed':True}
 raw=SOURCE.read_bytes();info=SOURCE.stat()
 backup=OP/('rg_moderation_pre_p39_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.py')
 with os.fdopen(os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as f:
  f.write(raw);f.flush();os.fsync(f.fileno())
 fd,tmp=tempfile.mkstemp(prefix='.news2_p39_',dir=str(SOURCE.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   f.write(text.encode('utf8'));f.flush();os.fsync(f.fileno())
  os.chmod(tmp,stat.S_IMODE(info.st_mode));os.chown(tmp,info.st_uid,info.st_gid)
  os.replace(tmp,str(SOURCE))
  if SOURCE.read_text('utf8')!=text:fail('AFTER_WRITE_MISMATCH')
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 return {'backup':str(backup),'source_updated':True}
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ('check','apply'):fail('USE_CHECK_OR_APPLY')
 checks();fds=[]
 try:
  fds.append(lock('callback_v29.lock'));fds.append(lock('controlled_handoff.lock'))
  final,changed=patch(SOURCE.read_text('utf8'))
  test=shadow_check()
  if sys.argv[1]=='check':
   output(status='NEWS2_P39_PREFLIGHT_PASS',shadow=test,update_required=changed,telegram_api_calls=0)
  else:
   result=apply(final,changed)
   output(status='NEWS2_P39_INSTALLED',result=result,shadow=test,
     telegram_api_calls=0,channel_publications=0,cron_changes=0)
 finally:
  for fd in reversed(fds):os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as e:
  output(status='NEWS2_P39_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__)
  sys.exit(1)
