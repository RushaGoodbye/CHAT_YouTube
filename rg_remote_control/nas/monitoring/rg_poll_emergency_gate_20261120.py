#!/usr/bin/env python3
"""Emergency fail-closed stop for unmoderated NAS NEWS2 polls. No Telegram calls."""
import ast,hashlib,json,os,stat,sys,tempfile
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
SRC=ROOT/'operator/news_rg_poll_moderation_v1.py'
BACK=ROOT/'rg_news2_fix_20261119/protected_backups'
OLD='b29d6fa26ec32e77ee51bfd51b1d99b1cb88110def57adb6204de2a14bd4501a'
MARK='RG_POLL_EMERGENCY_NO_PUBLICATION_20261120'
def sha(x):return hashlib.sha256(x).hexdigest()
def patch(source):
 tree=ast.parse(source)
 hits=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
  and n.func.id=='telegram' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='sendPoll']
 if len(hits)!=1:raise ValueError('SEND_POLL_CALL_COUNT_'+str(len(hits)))
 candidates=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
  and n.lineno<=hits[0].lineno<=n.end_lineno]
 if not candidates:raise ValueError('SEND_POLL_NOT_INSIDE_FUNCTION')
 target=min(candidates,key=lambda n:n.end_lineno-n.lineno)
 if not target.body or MARK in source:raise ValueError('UNSAFE_OR_ALREADY_PATCHED')
 first=target.body[0]
 lines=source.splitlines(keepends=True)
 pad=' '*first.col_offset
 if not pad or not lines[first.lineno-1].startswith(pad):raise ValueError('UNSAFE_INDENT')
 nl='\r\n' if '\r\n' in source else '\n'
 guard=pad+'# '+MARK+nl+pad+"raise RuntimeError('POLL_HUMAN_APPROVAL_REQUIRED_NO_AUTO_PUBLICATION')"+nl
 lines.insert(first.lineno-1,guard)
 new=''.join(lines)
 ast.parse(new)
 if new.count(MARK)!=1:raise ValueError('GATE_COUNT_INVALID')
 return new,target.name,hits[0].lineno
def atomic(path,data,mode):
 fd,tmp=tempfile.mkstemp(prefix='.rg_poll_gate_',dir=str(path.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(path))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run():
 if os.geteuid()!=0:raise ValueError('SUDO_REQUIRED')
 for d in (SRC.parent,BACK):
  if d.is_symlink() or not d.is_dir():raise ValueError('UNSAFE_DIRECTORY')
 if SRC.is_symlink() or not SRC.is_file():raise ValueError('UNSAFE_SOURCE')
 raw=SRC.read_bytes()
 if sha(raw)!=OLD:
  if MARK in raw.decode('utf8',errors='replace'):
   return {'status':'RG_POLL_EMERGENCY_ALREADY_BLOCKED','publications':0}
  raise ValueError('SOURCE_HASH_CHANGED_SAFE_STOP')
 amended,name,line=patch(raw.decode('utf8'))
 mode=stat.S_IMODE(SRC.stat().st_mode)
 if mode&0o022:raise ValueError('UNSAFE_FILE_PERMISSIONS')
 backup=BACK/('news_rg_poll_moderation_v1.before_emergency_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.py')
 fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:
  f.write(raw);f.flush();os.fsync(f.fileno())
 try:
  atomic(SRC,amended.encode('utf8'),mode)
  if sha(SRC.read_bytes())!=sha(amended.encode('utf8')):raise RuntimeError('POST_CHECK_FAILURE')
  ast.parse(SRC.read_text('utf8'))
 except Exception:
  atomic(SRC,raw,mode)
  raise RuntimeError('ROLLED_BACK')
 return {'status':'RG_POLL_AUTOPUBLISH_BLOCKED','function':name,'original_send_poll_line':line,
  'old_sha256':sha(raw),'new_sha256':sha(SRC.read_bytes()),'backup':str(backup),
  'telegram_calls':0,'publications':0,'other_news_modules_changed':0}
def selftest():
 sample="def send(telegram):\n    photo='x'\n    telegram('sendPoll', {'chat_id':1})\n"
 new,_,_=patch(sample)
 env={}
 exec(new,env)
 called=[]
 try:
  env['send'](lambda *x:called.append(x))
  raise AssertionError('GATE_FAILED')
 except RuntimeError as e:assert 'POLL_HUMAN_APPROVAL_REQUIRED' in str(e)
 assert not called
 print(json.dumps({'status':'RG_POLL_GATE_SELFTEST_PASS','telegram_calls':0,'publications':0}))
if __name__=='__main__':
 try:
  if '--selftest' in sys.argv:selftest()
  else:print(json.dumps(run(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_SAFE_STOP','reason':str(e)[:120],'telegram_calls':0,'publications':0}))
  sys.exit(2)
