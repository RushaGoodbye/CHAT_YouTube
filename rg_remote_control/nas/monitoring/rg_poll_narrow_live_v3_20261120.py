#!/usr/bin/env python3
"""NEWS2: replace broad emergency callback block with narrow sendPoll gate.
Fail closed on unexpected code. No network, Telegram calls, cron or other modules.
"""
import ast,hashlib,json,os,pathlib,stat,sys,tempfile,datetime
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
LIVE=ROOT/'operator/news_rg_poll_moderation_v1.py'
BACK=ROOT/'rg_news2_fix_20261119/protected_backups'
OLD='RG_POLL_EMERGENCY_NO_PUBLICATION_20261120'
OLD_ERROR='POLL_HUMAN_APPROVAL_REQUIRED_NO_AUTO_PUBLICATION'
NEW='RG_POLL_EXPLICIT_REVIEW_REQUIRED_V3'
NEW_ERROR='POLL_HUMAN_REVIEW_REQUIRED_NO_SEND'
def sha(b):return hashlib.sha256(b).hexdigest()
def is_raise(n,message):
 return (isinstance(n,ast.Raise) and isinstance(n.exc,ast.Call)
  and isinstance(n.exc.func,ast.Name) and n.exc.func.id=='RuntimeError'
  and len(n.exc.args)==1 and isinstance(n.exc.args[0],ast.Constant)
  and n.exc.args[0].value==message)
def is_poll(n):
 return (isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
  and n.func.id=='telegram' and n.args and isinstance(n.args[0],ast.Constant)
  and n.args[0].value=='sendPoll')
def repair(source):
 if source.count(OLD)!=1 or source.count(OLD_ERROR)!=1 or NEW in source:
  raise ValueError('OLD_GUARD_MISSING_OR_CHANGED')
 tree=ast.parse(source)
 funcs=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='callback']
 if len(funcs)!=1:raise ValueError('CALLBACK_COUNT_'+str(len(funcs)))
 fn=funcs[0]
 if not fn.body or not is_raise(fn.body[0],OLD_ERROR):
  raise ValueError('OLD_GUARD_NOT_FIRST_STATEMENT')
 entry=fn.body[0]
 lines=source.splitlines(keepends=True)
 i=entry.lineno-1
 if i<1 or entry.end_lineno!=entry.lineno:raise ValueError('OLD_GUARD_LAYOUT')
 pad=lines[i][:len(lines[i])-len(lines[i].lstrip(' \t'))]
 if (not pad or lines[i-1].strip()!='# '+OLD
     or lines[i-1][:len(lines[i-1])-len(lines[i-1].lstrip(' \t'))]!=pad
     or lines[i].strip()!="raise RuntimeError('"+OLD_ERROR+"')"):
  raise ValueError('OLD_GUARD_NOT_EXACT')
 calls=[n for n in ast.walk(tree) if is_poll(n)]
 if len(calls)!=1:raise ValueError('SENDPOLL_COUNT_'+str(len(calls)))
 call=calls[0]
 if not (fn.lineno<call.lineno<=fn.end_lineno):raise ValueError('SENDPOLL_WRONG_FUNCTION')
 statement=[n for n in ast.walk(fn) if isinstance(n,(ast.Assign,ast.Expr,ast.Return,ast.AnnAssign))
            and n.lineno==call.lineno and getattr(n,'value',None) is call]
 if len(statement)!=1:raise ValueError('SENDPOLL_STATEMENT_UNKNOWN')
 target=statement[0]
 if target.lineno<=entry.lineno:raise ValueError('SENDPOLL_BEFORE_GUARD')
 original=lines[target.lineno-1]
 indent=original[:len(original)-len(original.lstrip(' \t'))]
 if not indent or not original.lstrip().startswith(('res=','res =','telegram(')):
  raise ValueError('SENDPOLL_STATEMENT_FORMAT_CHANGED')
 nl='\r\n' if original.endswith('\r\n') else '\n'
 guard=indent+'# '+NEW+nl+indent+"raise RuntimeError('"+NEW_ERROR+"')"+nl
 lines.insert(target.lineno-1,guard)
 del lines[i-1:i+1]
 patched=''.join(lines)
 verified=ast.parse(patched)
 if patched.count(NEW)!=1 or OLD in patched or OLD_ERROR in patched:
  raise ValueError('PATCH_MARKERS_INVALID')
 if len([n for n in ast.walk(verified) if is_poll(n)])!=1:
  raise ValueError('SENDPOLL_ALTERED')
 return patched,call.lineno
def write(path,body,mode):
 fd,tmp=tempfile.mkstemp(prefix='.rg_poll_v3_',dir=str(path.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(body);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(path))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def apply():
 if os.geteuid()!=0:raise ValueError('ROOT_REQUIRED')
 if LIVE.is_symlink() or not LIVE.is_file() or BACK.is_symlink() or not BACK.is_dir():
  raise ValueError('UNSAFE_PATH')
 current=LIVE.read_bytes()
 source=current.decode('utf8')
 if NEW in source:raise ValueError('NARROW_GUARD_ALREADY_PRESENT')
 amended,line=repair(source)
 mode=stat.S_IMODE(LIVE.stat().st_mode)
 if mode&0o022:raise ValueError('UNSAFE_FILE_PERMISSIONS')
 t=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=BACK/('news_rg_poll_moderation_v1.before_v3_'+t+'.py')
 fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:
  f.write(current);f.flush();os.fsync(f.fileno())
 try:
  write(LIVE,amended.encode('utf8'),mode)
  if sha(LIVE.read_bytes())!=sha(amended.encode('utf8')):raise RuntimeError('POSTCHECK_FAILED')
 except Exception:
  write(LIVE,current,mode)
  raise RuntimeError('ROLLBACK_COMPLETED')
 return {'status':'RG_POLL_NARROW_V3_INSTALLED','original_send_poll_line':line,
  'old_sha256':sha(current),'new_sha256':sha(LIVE.read_bytes()),
  'backup':str(backup),'other_news_modules_changed':0,'telegram_calls':0,'publications':0}
def selftest():
 for assignment in ('res=','res ='):
  src=("def callback(update,telegram):\n"
    "    # RG_POLL_EMERGENCY_NO_PUBLICATION_20261120\n"
    "    raise RuntimeError('POLL_HUMAN_APPROVAL_REQUIRED_NO_AUTO_PUBLICATION')\n"
    "    value=5\n"
    "    if update:\n"
    "      "+assignment+"telegram('sendPoll',{'test':1})\n"
    "    return value\n")
  repaired,_=repair(src)
  ns={}
  exec(repaired,ns)
  called=[]
  assert ns['callback'](False,lambda *a:called.append(a))==5
  try:ns['callback'](True,lambda *a:called.append(a))
  except RuntimeError as e:assert str(e)==NEW_ERROR
  else:raise AssertionError('SENDPOLL_NOT_BLOCKED')
  assert not called
 print(json.dumps({'status':'RG_POLL_NARROW_V3_SELFTEST_PASS','telegram_calls':0,'publications':0}))
if __name__=='__main__':
 try:
  if len(sys.argv)==2 and sys.argv[1]=='--selftest':selftest()
  else:print(json.dumps(apply(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_NARROW_V3_SAFE_STOP','reason':str(e)[:120],
   'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
