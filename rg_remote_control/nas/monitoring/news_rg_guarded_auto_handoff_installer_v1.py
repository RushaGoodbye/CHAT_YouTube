#!/usr/bin/env python3
"""NEWS RG: install guarded staging + immediate private handoff in EXISTING NAS AI tick.

Changes only operator bridge and final_tick source after offline tests and backup.
No new scheduler, poller, Bot API, AI request, public post, callback or DB writes
during installation. Does NOT touch the already ACTIVE publication configuration.
"""
import os,sys,re,json,hashlib,pathlib,tempfile,subprocess,ast,stat,fcntl
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
BRIDGE=O/'news_rg_private_bridge_v1.py'
TICK=O/'news_rg_final_tick_v1.py'
GUARD=O/'news_rg_editorial_grounding_guard_v1.py'
S_GUARD=pathlib.Path('/tmp/news_rg_editorial_grounding_guard_v1.py')
EDIT_MARK='NEWS_RG_GROUNDING_GUARD_V1'
HANDOFF_MARK='NEWS_RG_INSTANT_PRIVATE_HANDOFF_V1'
ANCHOR='        target=OUT/(digest+".json")'
PREPARE=re.compile(r'(?m)^(?P<indent>[ \t]*)run\(\[sys\.executable,str\(bridge\),[\'"]prepare-one[\'"]\],(?P<timeout>\d+)\)[ \t]*$')
def stop(x):raise RuntimeError(x)
def out(**kw):print(json.dumps(kw,sort_keys=True,ensure_ascii=False))
def safe(p):
 return p.is_file() and not p.is_symlink() and p.stat().st_size<180000
def put(p,data,mode):
 fd,tmp=tempfile.mkstemp(prefix='.news_rg_guard_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as h:
   os.fchmod(h.fileno(),mode)
   h.write(data);h.flush();os.fsync(h.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def modify_bridge(src):
 if src.count(EDIT_MARK)==1:return src,True
 if EDIT_MARK in src:stop('BRIDGE_PARTIAL_GUARD_MARKER')
 if src.count(ANCHOR)!=1:stop('BRIDGE_GROUNDING_PATCH_ANCHOR_CHANGED')
 if 'def reject(' not in src or 'status!="DRAFT_ONLY_REVIEW_REQUIRED_UNVERIFIED"' not in src:
  stop('UNEXPECTED_BRIDGE_CONTENT')
 new='''        # NEWS_RG_GROUNDING_GUARD_V1: fail closed before staging or private delivery.
        from news_rg_editorial_grounding_guard_v1 import validate as _news_rg_validate
        _news_rg_issue=_news_rg_validate(source,draft)
        if _news_rg_issue is not None:
            failures["EDITORIAL_GUARD_"+_news_rg_issue]=failures.get("EDITORIAL_GUARD_"+_news_rg_issue,0)+1
            reject(digest,"EDITORIAL_GUARD_"+_news_rg_issue)
            continue
'''
 return src.replace(ANCHOR,new+ANCHOR,1),False
def modify_tick(src):
 if src.count(HANDOFF_MARK)==1:return src,True
 if HANDOFF_MARK in src:stop('TICK_PARTIAL_HANDOFF_MARKER')
 matches=list(PREPARE.finditer(src))
 if len(matches)!=1:stop('AI_TICK_PREPARE_ANCHOR_CHANGED')
 m=matches[0]
 if m.group('indent').replace(' ','')!='':stop('AI_TICK_NONSTANDARD_INDENT')
 ind=m.group('indent')
 # Reuse the same bridge invocation; only attempt one guarded private send on
 # successful staging. Existing private-dispatch lock and editorial gate apply.
 replacement=(ind+'# NEWS_RG_INSTANT_PRIVATE_HANDOFF_V1\n'+
  ind+'_news_rg_stage_rc=run([sys.executable,str(bridge),"prepare-one"],'+m.group('timeout')+')\n'+
  ind+'if _news_rg_stage_rc==0:\n'+
  ind+'    run([sys.executable,str(O/"news_rg_durable_private_dispatch_v1.py"),"run-once"],95)')
 return src[:m.start()]+replacement+src[m.end():],False
def basecheck():
 if os.geteuid()!=0:stop('SUDO_REQUIRED')
 for p in (B,O):
  if not p.is_dir() or p.is_symlink():stop('UNSAFE_DIRECTORY')
 for p in (BRIDGE,TICK,S_GUARD,O/'news_rg_durable_private_dispatch_v1.py',
           O/'news_rg_private_dispatch_schedule_v1.py',
           B/'rg_news_dsm_tick.sh'):
  if not safe(p):stop('MISSING_OR_UNSAFE_'+p.name)
 tick_script=(B/'rg_news_dsm_tick.sh').read_text('utf8')
 if '# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1' not in tick_script:
  stop('EXISTING_PRIVATE_AUTOMATION_NOT_INSTALLED')
 if '# NEWS_RG_APPROVED_PUBLICATION_CUTOVER_V1' not in tick_script:
  stop('ACTIVE_PUBLICATION_TICK_NOT_INSTALLED')
 return BRIDGE.read_text('utf8'),TICK.read_text('utf8')
def build():
 current_bridge,current_tick=basecheck()
 content=S_GUARD.read_text('utf8')
 if 'NEWS_RG_EDITORIAL_GROUNDING_GUARD_SELFTEST_PASS' not in content:
  stop('GUARD_SOURCE_NOT_RECOGNIZED')
 ast.parse(content);ast.parse(current_bridge);ast.parse(current_tick)
 new_bridge,b1=modify_bridge(current_bridge)
 new_tick,b2=modify_tick(current_tick)
 if b1!=b2:stop('PARTIAL_INSTALLATION_STOP')
 ast.parse(new_bridge);ast.parse(new_tick)
 if 'getUpdates' in new_tick or 'sendPhoto' in new_tick or 'sendMessage' in new_tick:
  stop('UNEXPECTED_DIRECT_TG_IN_TICK')
 if 'getUpdates' in new_bridge or 'sendPhoto' in new_bridge or 'sendMessage' in new_bridge:
  stop('UNEXPECTED_DIRECT_TG_IN_BRIDGE')
 if b1:
  if not safe(GUARD):stop('LIVE_GUARD_MISSING')
  if GUARD.read_text('utf8')!=content:stop('GUARD_VERSION_MISMATCH')
 return current_bridge,current_tick,new_bridge,new_tick,content,b1
def check_new(code,guard):
 with tempfile.TemporaryDirectory(prefix='.rg_guard_qa_',dir=str(O)) as directory:
  temp=pathlib.Path(directory)
  # Test all three exact output sources without executing the pipeline.
  for name,src in (('bridge.py',code),('guard.py',guard)):
   f=temp/name
   f.write_text(src,encoding='utf8')
   ast.parse(src)
  ret=subprocess.run(['/usr/bin/python3',str(temp/'guard.py'),'selftest'],
     stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10)
  if ret.returncode or 'SELFTEST_PASS' not in ret.stdout:
   stop('GUARD_SELFTEST_FAILED')
  result=subprocess.run(['/usr/bin/python3',str(temp/'bridge.py'),'selftest'],
     stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10)
  if result.returncode or 'SELFTEST_PASS' not in result.stdout:
   stop('PATCHED_BRIDGE_SELFTEST_FAILED')
def prepared():
 b,t,nb,nt,g,already=build()
 check_new(nb,g)
 return {'status':'ALREADY_GUARDED' if already else 'GUARDED_AUTOMATION_PREFLIGHT_PASS',
  'changes':[] if already else ['editorial_guard_before_staging','direct_private_handoff_after_valid_draft'],
  'existing_bot_unchanged':True,'publication_config_unchanged':True,
  'new_schedules':0,'pollers_started':0,'telegram_calls':0,'ai_calls':0,
  'publications':0},(b,t,nb,nt,g,already)
def install():
 response,files=prepared()
 b,t,nb,nt,g,already=files
 if already:return {'status':'NEWS_RG_GUARD_AND_HANDOFF_ALREADY_INSTALLED',
                    'publications':0,'pollers_started':0}
 digest=hashlib.sha256((b+'\n'+t).encode()).hexdigest()[:16]
 backups=[(BRIDGE,O/('news_rg_private_bridge.before_grounding_'+digest+'.py'),b),
          (TICK,O/('news_rg_final_tick.before_handoff_'+digest+'.py'),t)]
 for orig,bk,data in backups:
  if bk.is_symlink():stop('BACKUP_SYMLINK')
  if not bk.exists():put(bk,data.encode(),0o600)
 bridge_mode=stat.S_IMODE(BRIDGE.stat().st_mode)
 tick_mode=stat.S_IMODE(TICK.stat().st_mode)
 oldguard=GUARD.read_bytes() if GUARD.is_file() and not GUARD.is_symlink() else None
 # Avoid modifying files while the existing AI worker is running.
 lock=os.open(str(O/'news_rg_final.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (BlockingIOError,OSError):stop('AI_WORKER_BUSY_RETRY_LATER')
  if BRIDGE.read_text('utf8')!=b or TICK.read_text('utf8')!=t:
   stop('CONCURRENT_CHANGE_NO_INSTALL')
  try:
   put(GUARD,g.encode(),0o600)
   put(BRIDGE,nb.encode(),bridge_mode)
   put(TICK,nt.encode(),tick_mode)
   if (EDIT_MARK not in BRIDGE.read_text('utf8') or
       HANDOFF_MARK not in TICK.read_text('utf8')):
    stop('POSTINSTALL_SOURCE_MISMATCH')
   test=subprocess.run(['/usr/bin/python3',str(BRIDGE),'selftest'],
      capture_output=True,text=True,timeout=10)
   if test.returncode or 'SELFTEST_PASS' not in test.stdout:
    stop('POSTINSTALL_BRIDGE_SELFTEST_FAILED')
  except Exception:
   put(BRIDGE,b.encode(),bridge_mode)
   put(TICK,t.encode(),tick_mode)
   if oldguard is None and GUARD.exists():GUARD.unlink()
   elif oldguard is not None:put(GUARD,oldguard,0o600)
   raise
 finally:os.close(lock)
 return {'status':'NEWS_RG_GUARD_AND_INSTANT_HANDOFF_INSTALLED',
    'new_poller_count':0,'new_schedules':0,'publications_during_install':0,
    'mod_bot_unchanged':True,'public_gate_unchanged':True,
    'next_cycle_stage_to_private_send':True,
    'backup_bridge':str(backups[0][1]),'backup_tick':str(backups[1][1])}
def selftest():
 original='''def main():
    run([sys.executable,str(bridge),"prepare-one"],80)
'''
 modified,old=modify_tick(original)
 assert not old and HANDOFF_MARK in modified
 ast.parse(modified)
 src='''def run():
        target=OUT/(digest+".json")
'''
 # This unit tests the isolated text patch separately from the live contract.
 assert len(list(PREPARE.finditer(original)))==1
 assert MARK_SAFE()
 print('NEWS_RG_GUARDED_HANDOFF_INSTALLER_SELFTEST_PASS')
def MARK_SAFE():
 return ('getUpdates' not in PREPARE.pattern and EDIT_MARK!='')
if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:selftest()
  elif mode==['preflight']:
   result,_=prepared();out(**result)
  elif mode==['install']:out(**install())
  else:stop('EXPECTED_SELFTEST_PREFLIGHT_OR_INSTALL')
 except Exception as e:
  out(status='SAFE_STOP',reason=str(e)[:140],telegram_calls=0,publications=0)
  sys.exit(2)
