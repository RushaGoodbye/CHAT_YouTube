#!/usr/bin/env python3
"""NEWS RG: safely connect ne1 editorial callbacks to the EXISTING guarded worker.
One existing polling owner; no new poller, outbound message, or public publication.
"""
import os,sys,json,pathlib,re,ast,hashlib,tempfile,subprocess,stat
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
WORKER=O/'rg_news2_p31_guarded_callback_once.py'
OWNER=O/'callback_v29.py'
MOD=B/'rg_moderation.py'
HOOK=O/'news_rg_editorial_callbacks_v1.py'
MARK='# NEWS_RG_NE1_OWNER_ROUTE_V1'

def emit(**x):
 print(json.dumps(x,ensure_ascii=False,sort_keys=True))

def reject(message):
 raise RuntimeError(message)

def atomic_file(dest,data,mode):
 fd,tmp=tempfile.mkstemp(prefix='.news_rg_route_',dir=str(dest.parent))
 try:
  with os.fdopen(fd,'wb') as out:
   os.fchmod(out.fileno(),mode)
   out.write(data);out.flush();os.fsync(out.fileno())
  os.replace(tmp,dest)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def build(src):
 if MARK in src:
  return src,True
 if src.count("val.startswith('ph1:')")!=1:
  reject('CALLBACK_ALLOWLIST_PATTERN_CHANGED')
 original="val.startswith('ph1:')"
 amended="val.startswith('ph1:') or val.startswith('ne1:')"
 if 'FOREIGN_CALLBACK_FAMILY_DETECTED_NOT_ACKNOWLEDGED' not in src:
  reject('FOREIGN_CALLBACK_GUARD_MISSING')
 if 'old_api=m.api' not in src or 'm.process_callback(u,cfg)' not in src:
  reject('KNOWN_CALLBACK_WORKER_CONTRACT_CHANGED')
 if not re.search(r'(?m)^\s*statuses\s*=\s*\[\]',src):
  reject('CALLBACK_STATUS_ARRAY_NOT_FOUND')
 if not re.search(r'(?m)^\s*ui_results\s*=\s*\[\]',src):
  reject('CALLBACK_UI_ARRAY_NOT_FOUND')
 # The guard is only extended for the new, isolated editorial namespace.
 modified=src.replace(original,amended,1)
 pat=re.compile(r"(?m)^(?P<outer>[ \t]*)for u in ups:\r?\n(?P<inner>[ \t]*)q=u\.get\(['\"]callback_query['\"]\) or \{\}[ \t]*\r?\n")
 occurrences=list(pat.finditer(modified))
 if len(occurrences)!=1:reject('WORKER_UPDATE_LOOP_ANCHOR_NOT_UNIQUE')
 match=occurrences[0]
 outer=match.group('outer');inner=match.group('inner')
 if len(inner)<=len(outer) or '\t' in inner:reject('WORKER_INDENT_UNEXPECTED')
 lines=[
  MARK,
  'if isinstance(q,dict) and str(q.get("data","")).startswith("ne1:"):',
  '    _ne_decision=m.process_callback(u,cfg)',
  '    _ne_status=str(_ne_decision.get("status","EDITORIAL_UNKNOWN"))[:90]',
  '    statuses.append(_ne_status)',
  '    _ne_ack=False',
  '    if q.get("id"):',
  '        try:',
  '            old_api("answerCallbackQuery",{"callback_query_id":q["id"],"text":_ne_status})',
  '            _ne_ack=True',
  '        except Exception:',
  '            pass',
  '    ui_results.append({"kind":"EDITORIAL_BUTTON","action":"editorial","confirmation_sent":_ne_ack})',
  '    off=max(off,u["update_id"]+1)',
  '    putoff(m,off)',
  '    continue'
 ]
 insertion=''.join(inner+line+'\n' for line in lines)
 modified=modified[:match.end()]+insertion+modified[match.end():]
 ast.parse(modified)
 if modified.count(MARK)!=1 or modified.count("val.startswith('ne1:')")!=1:
  reject('NE1_ROUTE_PATCH_CONTRACT_FAILED')
 return modified,False

def run(mode):
 if os.geteuid()!=0:reject('SUDO_REQUIRED')
 for path in (B,O):
  if not path.is_dir() or path.is_symlink():reject('UNSAFE_PROJECT_DIRECTORY')
 for path in (WORKER,OWNER,MOD,HOOK):
  if not path.is_file() or path.is_symlink():reject('UNSAFE_EXPECTED_FILE_'+path.name)
 old=WORKER.read_text(encoding='utf-8')
 if 'WORKER=O/\'rg_news2_p31_guarded_callback_once.py\'' not in OWNER.read_text(encoding='utf-8'):
  reject('CALLBACK_OWNER_CHANGED')
 if '# NEWS_RG_EDITORIAL_HOOK_V1' not in MOD.read_text(encoding='utf-8'):
  reject('NEWS_RG_EDITORIAL_HOOK_MISSING')
 hook_text=HOOK.read_text(encoding='utf-8')
 if 'EDITORIAL_ACCEPTED_NO_PUBLICATION' not in hook_text or 'ne1:(accept|reject)' not in hook_text:
  reject('EDITORIAL_CALLBACK_MODULE_CHANGED')
 updated,already=build(old)
 if already:return {'status':'NE1_ROUTE_ALREADY_INSTALLED','publications':0,'second_poller':False}
 orig_hash=hashlib.sha256(old.encode()).hexdigest()
 if mode=='preflight':
  return {'status':'NE1_ROUTE_PREFLIGHT_PASS','source_sha256':orig_hash[:16],
          'changes':['allowlist_ne1','process_existing_editorial_callback','ack_editorial_button'],
          'telegram_calls':0,'publications':0}
 mode_bits=stat.S_IMODE(WORKER.stat().st_mode)
 backup=O/('rg_news2_p31.before_ne1_'+orig_hash[:16]+'.py')
 if backup.exists() and backup.is_symlink():reject('BACKUP_SYMLINK')
 if not backup.exists():atomic_file(backup,old.encode('utf-8'),0o600)
 try:
  atomic_file(WORKER,updated.encode('utf-8'),mode_bits)
  test=subprocess.run(['/usr/bin/python3','-m','py_compile',str(WORKER)],
                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12)
  if test.returncode:reject('POSTINSTALL_SYNTAX_FAILED')
  live=WORKER.read_text('utf-8')
  if live!=updated or live.count(MARK)!=1:reject('POSTINSTALL_MISMATCH')
 except Exception:
  atomic_file(WORKER,old.encode('utf-8'),mode_bits)
  raise
 return {'status':'NEWS_RG_NE1_WORKER_ROUTE_INSTALLED','backup':str(backup),
         'single_existing_owner':True,'second_poller':False,
         'previous_callbacks_preserved':True,'telegram_calls':0,'publications':0}

def selftest():
 sample = """def once():
 statuses=[]
 ui_results=[]
 old_api=m.api
 for u in ups:
  q=u.get('callback_query') or {}
  parts=str(q.get('data','')).split(':')
  ret=m.process_callback(u,cfg)
  statuses.append(str(ret.get('status','')))
  off=max(off,u['update_id']+1)
  putoff(m,off)
 if not (val.startswith('rg3:') or val.startswith('rgprobe25:') or val.startswith('ph1:')):
  raise RuntimeError('FOREIGN_CALLBACK_FAMILY_DETECTED_NOT_ACKNOWLEDGED')
"""
 new,already=build(sample)
 assert not already and MARK in new and "val.startswith('ne1:')" in new
 assert 'ui_results.append' in new
 assert build(new)[1]
 print('NEWS_RG_NE1_WORKER_PATCH_SELFTEST_PASS')

if __name__=='__main__':
 try:
  args=sys.argv[1:]
  if args==['selftest']:selftest()
  elif args in (['preflight'],['install']):emit(**run(args[0]))
  else:reject('MODE_NOT_SUPPORTED')
 except Exception as exc:
  emit(status='SAFE_STOP',error_class=str(exc)[:120],
       telegram_calls=0,publications=0);sys.exit(2)
