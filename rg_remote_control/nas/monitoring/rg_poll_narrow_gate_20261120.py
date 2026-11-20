#!/usr/bin/env python3
"""NEWS2: narrow emergency poll gate + read-only code contract diagnosis.
Never calls Telegram. Does not enable scheduled polls or touch other modules.
Requires the exact 2026-11-20 emergency version and its verified original backup.
"""
import ast, hashlib, json, os, pathlib, re, stat, sys, tempfile, datetime
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
LIVE=ROOT/'operator/news_rg_poll_moderation_v1.py'
BACK=ROOT/'rg_news2_fix_20261119/protected_backups'
PREV='37cfdbf0e7be2e40ecba8be1d0a9d73e64990a45136076f12f52d7a603d72a90'
ORIGINAL='b29d6fa26ec32e77ee51bfd51b1d99b1cb88110def57adb6204de2a14bd4501a'
MARK='RG_POLL_EXPLICIT_REVIEW_REQUIRED_V2'
def sha(b):return hashlib.sha256(b).hexdigest()
def call_match(n):
 return isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='telegram' and bool(n.args) and isinstance(n.args[0],ast.Constant) and n.args[0].value=='sendPoll'
def create_patch(source):
 tree=ast.parse(source)
 calls=[n for n in ast.walk(tree) if call_match(n)]
 if len(calls)!=1:raise ValueError('SEND_POLL_CALL_COUNT_'+str(len(calls)))
 c=calls[0]
 # Insert into the complete, unique sendPoll assignment, not the function entry.
 nodes=[n for n in ast.walk(tree) if isinstance(n,(ast.Assign,ast.Expr,ast.Return))
   and n.lineno==c.lineno and isinstance(n.value,ast.Call) and n.value is c]
 if len(nodes)!=1:raise ValueError('SEND_POLL_STATEMENT_COUNT_'+str(len(nodes)))
 target=nodes[0]
 enclosing=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
   and n.lineno<=target.lineno<=n.end_lineno]
 if not enclosing:raise ValueError('SEND_POLL_FUNCTION_MISSING')
 owner=min(enclosing,key=lambda n:n.end_lineno-n.lineno)
 lines=source.splitlines(keepends=True)
 original=lines[target.lineno-1]
 indent=original[:len(original)-len(original.lstrip(' \t'))]
 if len(indent)<2:raise ValueError('UNSAFE_INDENT')
 newline='\r\n' if original.endswith('\r\n') else '\n'
 guard=(indent+'# '+MARK+newline+
        indent+"raise RuntimeError('POLL_HUMAN_REVIEW_REQUIRED_NO_SEND')"+newline)
 lines.insert(target.lineno-1,guard)
 patched=''.join(lines)
 ast.parse(patched)
 if patched.count(MARK)!=1:raise ValueError('GUARD_COUNT_INCORRECT')
 return patched,owner,c
def persist(path,payload,mode):
 fd,tmp=tempfile.mkstemp(prefix='.rg_poll_narrow_',dir=str(path.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode)
   f.write(payload);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(path))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def report_context(src,owner,c):
 # Structural metadata only: never print code strings or possible credentials.
 return {'callback_function':owner.name,
         'callback_arguments':[n.arg for n in owner.args.args],
         'poll_call_line_original':c.lineno}
def main():
 if os.geteuid()!=0:raise ValueError('ROOT_REQUIRED')
 if LIVE.is_symlink() or not LIVE.is_file() or BACK.is_symlink() or not BACK.is_dir():
  raise ValueError('UNSAFE_PATH')
 current=LIVE.read_bytes()
 if sha(current)!=PREV:
  if MARK in current.decode('utf8',errors='replace'):
   print(json.dumps({'status':'RG_POLL_NARROW_GATE_ALREADY_INSTALLED','publications':0,'telegram_calls':0}))
   return
  raise ValueError('UNEXPECTED_LIVE_SHA_SAFE_STOP')
 candidates=[]
 for b in BACK.glob('news_rg_poll_moderation_v1.before_emergency_*.py'):
  if b.is_symlink() or not b.is_file():continue
  data=b.read_bytes()
  if sha(data)==ORIGINAL:candidates.append((b,data))
 if len(candidates)!=1:raise ValueError('ORIGINAL_BACKUP_NOT_UNIQUE_OR_MISSING')
 oldpath,sourcebytes=candidates[0]
 source=sourcebytes.decode('utf8')
 patched,owner,c=create_patch(source)
 mode=stat.S_IMODE(LIVE.stat().st_mode)
 if mode&0o022:raise ValueError('UNSAFE_PERMISSIONS')
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=BACK/('news_rg_poll_moderation_v1.before_narrow_'+stamp+'.py')
 fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:
  f.write(current);f.flush();os.fsync(f.fileno())
 try:
  persist(LIVE,patched.encode('utf8'),mode)
  if sha(LIVE.read_bytes())!=sha(patched.encode('utf8')):raise RuntimeError('WRITE_VERIFICATION_FAILED')
  t=ast.parse(LIVE.read_text('utf8'))
  gates=[n for n in ast.walk(t) if isinstance(n,ast.Raise) and n.lineno==c.lineno+1]
  if len(gates)!=1:raise RuntimeError('GUARD_NOT_AT_SEND_POLL')
 except Exception:
  persist(LIVE,current,mode)
  raise RuntimeError('ROLLBACK_COMPLETED')
 print(json.dumps({'status':'RG_POLL_NARROW_GATE_INSTALLED',
  'current_sha256':sha(LIVE.read_bytes()),'restored_from_original_sha256':sha(sourcebytes),
  'backup':str(backup),
  'sendPoll_guarded':True,
  'other_callback_statements_not_blocked_by_emergency_entry_guard':True,
  'structure':report_context(source,owner,c),
  'telegram_calls':0,'publications':0,'other_news_modules_changed':0},ensure_ascii=False,indent=2))
def selftest():
 sample='def callback(update, cfg, telegram):\n    status="ok"\n    if update:\n        res=telegram("sendPoll",{"question":"test"})\n    return status\n'
 amended,owner,call=create_patch(sample)
 values={}
 exec(amended,values)
 assert values['callback'](False,{},lambda *a:None)=='ok'
 attempts=[]
 try:values['callback'](True,{},lambda *a:attempts.append(a))
 except RuntimeError as e:assert str(e)=='POLL_HUMAN_REVIEW_REQUIRED_NO_SEND'
 else:raise AssertionError('POLL_NOT_BLOCKED')
 assert not attempts
 assert 'raise RuntimeError' in amended and amended.index('raise RuntimeError')>amended.index('if update:')
 print(json.dumps({'status':'RG_POLL_NARROW_GATE_SELFTEST_PASS','telegram_calls':0,'publications':0}))
if __name__=='__main__':
 try:
  if len(sys.argv)==2 and sys.argv[1]=='--selftest':selftest()
  else:main()
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_NARROW_GATE_SAFE_STOP','error':str(e)[:140],
                    'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
