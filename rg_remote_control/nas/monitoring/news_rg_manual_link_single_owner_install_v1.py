#!/usr/bin/env python3
"""NEWS RG: safely restore manual links in the existing sole Telegram update owner.

Edit ONLY the pinned existing single-owner worker's allowed_updates + one message
route and install a strictly gated private-stage helper. No new getUpdates,
pollers, cron, bot, direct publication or historic Telegram update replay.
Back up original worker, rollback on every installation exception.
"""
import os,sys,json,re,ast,subprocess,pathlib,hashlib,stat,tempfile,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
WORKER=O/'rg_news2_p31_guarded_callback_once.py'
OWNER=O/'callback_v29.py'
MOD=B/'rg_moderation.py'
HELPER=O/'news_rg_manual_link_intake_v1.py'
SOURCE=pathlib.Path('/tmp/news_rg_manual_link_intake_v1.py')
ACT=O/'news_rg_manual_link_activation_v1.json'
BACKUP=O/'rg_news2_p31.before_manual_link_v1.backup'
ROUTE_TAG='# NEWS_RG_MANUAL_LINK_SINGLE_OWNER_V1'
EXPECTED_WORKER_SHA16='d45141664b5aba6d'
REVIEW=O/'news_rg_durable_private_dispatch_v1.py'
def fail(s):raise RuntimeError(s)
def emit(**d):print(json.dumps(d,ensure_ascii=False,sort_keys=True))
def read(p,limit=500000):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:fail('SOURCE_MISSING_OR_UNSAFE_'+p.name)
 return p.read_text('utf8')
def pin(text):return hashlib.sha256(text.encode('utf8')).hexdigest()[:16]
def builder(old):
 if ROUTE_TAG in old:fail('MANUAL_ROUTE_ALREADY_PRESENT')
 if old.count('# NEWS_RG_NE1_OWNER_ROUTE_V1')!=1:fail('EDITED_CALLBACK_OWNER_UNKNOWN')
 if 'FOREIGN_CALLBACK_FAMILY_DETECTED_NOT_ACKNOWLEDGED' not in old:
  fail('FOREIGN_CALLBACK_GUARD_MISSING')
 if 'old_api=m.api' not in old or 'putoff(m,off)' not in old or 'm.process_callback(u,cfg)' not in old:
  fail('EXPECTED_SINGLE_OWNER_VARIABLES_MISSING')
 ast.parse(old)
 # Find exactly one literal getUpdates allowed_updates argument for callbacks.
 lines=old.splitlines(keepends=True)
 matches=[i for i,line in enumerate(lines) if 'allowed_updates' in line and 'callback_query' in line]
 if len(matches)!=1:fail('ALLOWED_UPDATES_ENTRY_NOT_UNIQUE')
 i=matches[0]
 if 'getUpdates' not in lines[i]:fail('ALLOWED_UPDATES_NOT_ON_GETUPDATES')
 pattern=re.compile(r'\[\s*([\'"])callback_query\1\s*\]')
 if len(pattern.findall(lines[i]))!=1:fail('CALLBACK_ONLY_ALLOWLIST_NOT_RECOGNIZED')
 lines[i]=pattern.sub("['callback_query','message']",lines[i],count=1)
 changed=''.join(lines)
 # Unique legacy-approved anchor after the *second* loop for u in ups.
 pat=re.compile(r"(?m)^(?P<outer>[ \t]*)for u in ups:\r?\n(?P<inner>[ \t]*)q=u\.get\(['\"]callback_query['\"]\) or \{\}[ \t]*\r?\n")
 occurrences=list(pat.finditer(changed))
 if len(occurrences)!=1:fail('UPDATE_MESSAGE_LOOP_ANCHOR_NOT_UNIQUE')
 match=occurrences[0]
 outer,inner=match.group('outer'),match.group('inner')
 if len(inner)<=len(outer) or '\t' in inner:fail('UPDATE_LOOP_INDENT_INVALID')
 # Message processing executes exclusively within existing for-updates loop.
 # It is handled BEFORE the callback-family allowlist, so callbacks remain
 # identical, and message update offsets are persisted in the same owner.
 additions=[
   ROUTE_TAG,
   "if isinstance(u.get('message'),dict):",
   "    import news_rg_manual_link_intake_v1 as _rg_manual",
   "    _rg_manual_result=_rg_manual.handle(u,cfg,old_api)",
   "    if isinstance(locals().get('statuses'),list):",
   "        statuses.append(str(_rg_manual_result.get('status','MANUAL_UNKNOWN'))[:80])",
   "    off=max(off,u['update_id']+1)",
   "    putoff(m,off)",
   "    if _rg_manual_result.get('status')=='MANUAL_LINK_STAGED':",
   "        _rg_manual.dispatch_once_async()",
   "    continue"
 ]
 insertion=''.join(inner+line+'\n' for line in additions)
 amended=changed[:match.end()]+insertion+changed[match.end():]
 ast.parse(amended)
 if amended.count(ROUTE_TAG)!=1 or amended.count("['callback_query','message']")!=1:
  fail('AMENDED_WORKER_CONTRACT_FAIL')
 if old.count('getUpdates')!=amended.count('getUpdates'):
  fail('NEW_POLLING_REFERENCE_FORBIDDEN')
 if old.count('m.process_callback(u,cfg)')!=amended.count('m.process_callback(u,cfg)'):
  fail('CALLBACK_HANDLER_CHANGED')
 if old.count('putoff(m,off)')+1!=amended.count('putoff(m,off)'):
  fail('MESSAGE_OFFSET_PERSISTENCE_MISSING')
 return amended
def atomic(p,content,mode):
 fd,tmp=tempfile.mkstemp(prefix='.news_rg_manual_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode)
   if p.is_file() and not p.is_symlink():
    st=p.stat();os.fchown(f.fileno(),st.st_uid,st.st_gid)
   f.write(content);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def check():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 for p in (B,O):
  if p.is_symlink() or not p.is_dir():fail('BASE_DIRECTORY_UNSAFE')
 for p in (SOURCE,WORKER,OWNER,MOD,REVIEW):
  read(p)
 if read(OWNER).count("WORKER=O/'rg_news2_p31_guarded_callback_once.py'")!=1:
  fail('CALLBACK_OWNER_CHANGED')
 if '# NEWS_RG_EDITORIAL_HOOK_V1' not in read(MOD):fail('EDITORIAL_HOOK_MISSING')
 if '# NEWS_RG_NE1_OWNER_ROUTE_V1' not in read(WORKER):fail('ACTIVE_ROUTE_CHANGED')
 if ACT.exists() or HELPER.exists():
  if (not ACT.is_symlink() and not HELPER.is_symlink() and
      ACT.is_file() and HELPER.is_file()):
   activation=json.loads(ACT.read_text('utf8'))
   live=read(WORKER)
   if activation.get('status')=='ACTIVE' and ROUTE_TAG in live:
    return {'status':'MANUAL_LINK_ALREADY_ACTIVE'},None
  fail('PARTIAL_OR_FOREIGN_MANUAL_INSTALL')
 if BACKUP.is_symlink() or BACKUP.exists():fail('BACKUP_ALREADY_EXISTS')
 src=read(SOURCE)
 if 'NEWS_RG_MANUAL_LINK_INTAKE_V1' not in src or 'def dispatch_once_async' not in src or 'class PublicPostReader' not in src:
  fail('UNKNOWN_HELPER_SOURCE')
 if re.search(r'(?m)^\s*(?:import|from)\s+(?:rg_telegram_nas_native_bot|importlib)',src):
  fail('UNEXPECTED_LEGACY_IMPORT')
 if pin(read(WORKER))!=EXPECTED_WORKER_SHA16:
  fail('ACTIVE_WORKER_HASH_CHANGED_NO_PATCH')
 _=builder(read(WORKER))
 sub=subprocess.run(['/usr/bin/python3',str(SOURCE),'selftest'],
  capture_output=True,text=True,timeout=12)
 if sub.returncode or 'SELFTEST_PASS' not in sub.stdout:fail('HELPER_SELFTEST_FAILED')
 return {'status':'MANUAL_LINK_RESTORE_PREFLIGHT_PASS',
  'single_owner':True,'worker_pin_verified':True,'self_contained_reader':True,
  'allowed_update_types_after':['callback_query','message'],
  'new_pollers':0,'new_schedules':0,'publications':0,'telegram_calls':0,
  'patches':['enable_message_update_type','route_message_before_callback_guard',
    'stage_for_human_review','one_shot_private_handoff']},(read(WORKER),src)
def install():
 preview,buff=check()
 if buff is None:return preview
 original,helper=buff
 updated=builder(original)
 mode=stat.S_IMODE(WORKER.stat().st_mode)
 staged=[]
 try:
  atomic(BACKUP,original.encode('utf8'),0o600);staged.append(BACKUP)
  atomic(HELPER,helper.encode('utf8'),0o600);staged.append(HELPER)
  # Open the manual intake gate only for NEW message.date at this point.
  act={'schema':'NEWS_RG_MANUAL_LINK_ACTIVATION_V1','status':'ACTIVE',
       'activated_at':int(time.time()),'historic_updates_replay':False,
       'new_poller':False,'public_publication':'HUMAN_APPROVAL_ONLY',
       'worker_sha_before':pin(original),'worker_sha_after':pin(updated)}
  atomic(ACT,json.dumps(act,ensure_ascii=False,sort_keys=True).encode(),0o600);staged.append(ACT)
  if read(WORKER)!=original:fail('CONCURRENT_WORKER_CHANGE')
  atomic(WORKER,updated.encode('utf8'),mode)
  test=subprocess.run(['/usr/bin/python3','-m','py_compile',str(WORKER)],capture_output=True,timeout=12)
  if test.returncode:fail('POSTINSTALL_WORKER_SYNTAX_FAIL')
  if read(WORKER)!=updated:fail('POSTINSTALL_WORKER_MISMATCH')
  return {'status':'NEWS_RG_MANUAL_LINK_RESTORED','single_owner':True,
    'allowed_updates':['callback_query','message'],'private_review_required':True,
    'publication_only_after_approval':True,'legacy_bot_started':False,
    'pollers_started':0,'new_dsm_tasks':0,'publications_during_install':0,
    'new_messages_only':True,'backup_present':True}
 except Exception:
  if read(WORKER)==updated:atomic(WORKER,original.encode('utf8'),mode)
  for p in reversed(staged):
   try:
    if p.is_file() and not p.is_symlink():p.unlink()
   except OSError:pass
  raise
def selftest():
 fake="""#!/usr/bin/env python3
def main():
 statuses=[];ui_results=[]
 old_api=m.api
 ups=old_api('getUpdates',{'offset':0,'allowed_updates':['callback_query']})
 for u in ups:
  if u.get('callback_query'):pass
 for u in ups:
  q=u.get('callback_query') or {}
  if isinstance(q,dict) and str(q.get('data','')).startswith('ne1:'):
   _ne_decision=m.process_callback(u,cfg)
   off=max(off,u['update_id']+1)
   putoff(m,off)
   continue
  val=str(q.get('data',''))
  if not (val.startswith('rg3:') or val.startswith('ph1:')):
   raise RuntimeError('FOREIGN_CALLBACK_FAMILY_DETECTED_NOT_ACKNOWLEDGED')
  ret=m.process_callback(u,cfg)
  off=max(off,u['update_id']+1)
  putoff(m,off)
# NEWS_RG_NE1_OWNER_ROUTE_V1
"""
 amended=builder(fake)
 assert "'allowed_updates':['callback_query','message']" in amended
 assert amended.count(ROUTE_TAG)==1
 assert amended.index("q=u.get('callback_query') or {}")<amended.index("if isinstance(u.get('message'),dict):")<amended.index("val=str(q.get('data',''))")
 assert 'news_rg_manual_link_intake_v1' in amended
 assert amended.count('getUpdates')==fake.count('getUpdates')
 print('NEWS_RG_MANUAL_SINGLE_OWNER_INSTALLER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['preflight']:
   result,_=check();emit(**result)
  elif sys.argv[1:]==['install']:emit(**install())
  else:fail('EXPECTED_SELFTEST_PREFLIGHT_INSTALL')
 except Exception as e:
  emit(status='SAFE_STOP',reason=str(e)[:100] if isinstance(e,RuntimeError) else type(e).__name__,
   second_poller_started=False,telegram_calls=0,publications=0)
  sys.exit(2)
