#!/usr/bin/env python3
"""RG NEWS2 poll hard stop v6. No publication until moderated pipeline is verified.
Matches live code structure, no assumptions about earlier patch SHA.
"""
import ast, hashlib, json, os, stat, tempfile, sys
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
LIVE=ROOT/'operator/news_rg_poll_moderation_v1.py'
QA=ROOT/'operator/news_rg_poll_quality_v1.py'
BACK=ROOT/'rg_news2_fix_20261119/protected_backups'
QA_SHA='bc585371bc693093a5469ca7abc32a09a35a9ebdec67f919223c52a1c05b4e22'
MARK='RG_POLL_V6_HUMAN_APPROVAL_GATE_20261120'

def sha(data): return hashlib.sha256(data).hexdigest()
def require(ok, message):
 if not ok: raise ValueError(message)
def getfunc(tree,name):
 hits=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
 require(len(hits)==1,'FUNCTION_COUNT_CHANGED_'+name)
 return hits[0]
def is_action(node,value):
 return isinstance(node,ast.If) and isinstance(node.test,ast.Compare) and isinstance(node.test.left,ast.Name) and node.test.left.id=='action' and len(node.test.ops)==1 and isinstance(node.test.ops[0],ast.Eq) and len(node.test.comparators)==1 and isinstance(node.test.comparators[0],ast.Constant) and node.test.comparators[0].value==value
def make_patch(source):
 require(MARK not in source,'ALREADY_GATED')
 tree=ast.parse(source)
 cb=getfunc(tree,'callback');valid=getfunc(tree,'validate_poll');getfunc(tree,'make_variant')
 require(len(cb.args.args)==2,'CALLBACK_SIGNATURE_CHANGED')
 require(all(a.arg in ('update','cfg') for a in cb.args.args),'CALLBACK_ARGS_CHANGED')
 require(len([n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='telegram' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='sendPoll'])==1,'SENDPOLL_COUNT_CHANGED')
 require(len([n for n in ast.walk(cb) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='send_photo'])==1,'PHOTO_SEND_COUNT_CHANGED')
 pub=[n for n in ast.walk(cb) if is_action(n,'pub')]
 require(len(pub)==2,'PUB_BRANCH_COUNT_CHANGED')
 claim=[n for n in pub if n.body and isinstance(n.body[0],ast.If) and
        "state.get('publications')" in (ast.get_source_segment(source,n.body[0]) or '')]
 require(len(claim)==1,'CLAIM_BRANCH_CHANGED')
 pubnode=claim[0]
 require(any(isinstance(n,ast.Assign) and 'PUBLIC_SEND_UNCERTAIN' in (ast.get_source_segment(source,n) or '')
             for n in ast.walk(pubnode)),'PUBLIC_CLAIM_MISSING')
 returns=[n for n in valid.body if isinstance(n,ast.Return) and isinstance(n.value,ast.Constant) and n.value.value is True]
 require(len(returns)==1 and valid.body[-1] is returns[0],'VALIDATOR_RETURN_CHANGED')
 lines=source.splitlines(keepends=True)
 newline='\r\n' if '\r\n' in source else '\n'
 def pad(line):
  raw=lines[line-1];p=raw[:len(raw)-len(raw.lstrip(' \t'))]
  require('	' not in p,'TABS_IN_INDENT')
  return p
 validator_line=returns[0].lineno
 require(lines[validator_line-1].strip()=='return True','VALIDATOR_ANCHOR_CHANGED')
 callback_line=pubnode.body[0].lineno
 require(lines[callback_line-1].lstrip().startswith("if state.get('publications')"),'PUB_GUARD_ANCHOR_CHANGED')
 pv=pad(validator_line); pp=pad(callback_line)
 require(pv and pp,'INVALID_INDENT')
 validator_gate=(pv+'# '+MARK+' QUALITY'+newline+
  pv+'from news_rg_poll_quality_v1 import validate as _rg_poll_editorial_validate'+newline+
  pv+'_rg_poll_editorial_validate(question,options)'+newline)
 pub_gate=(pp+'# '+MARK+' FAIL_CLOSED'+newline+
  pp+'try:'+newline+
  pp+' from news_rg_poll_quality_v1 import validate as _rg_poll_editorial_validate'+newline+
  pp+" _rg_poll_editorial_validate(v.get('question'),v.get('options'))"+newline+
  pp+'except Exception:'+newline+
  pp+" return {'status':'POLL_EDITORIAL_QA_FAILED_NO_PUBLICATION','publications':0}"+newline+
  pp+"return {'status':'POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL','publications':0}"+newline)
 for linenum,block in sorted([(validator_line,validator_gate),(callback_line,pub_gate)],reverse=True):
  lines.insert(linenum-1,block)
 result=''.join(lines)
 ast.parse(result)
 require(result.count(MARK)==2,'GATE_COUNT_FAILED')
 require(result.index('POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL')<result.index("v['status']='PUBLIC_SEND_UNCERTAIN'"),'GATE_ORDER_FAILED')
 return result, {'validator_line':validator_line,'public_gate_line':callback_line}

def atomic(path,data,mode):
 fd,tmp=tempfile.mkstemp(prefix='.rg_poll_v6_',dir=str(path.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(path))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def apply():
 require(os.geteuid()==0,'ROOT_REQUIRED')
 for directory in (LIVE.parent,BACK):
  require(directory.is_dir() and not directory.is_symlink(),'UNSAFE_DIRECTORY')
 for path in (LIVE,QA):
  require(path.is_file() and not path.is_symlink(),'UNSAFE_FILE')
 require(sha(QA.read_bytes())==QA_SHA,'QUALITY_MODULE_SHA_CHANGED')
 old=LIVE.read_bytes()
 require(len(old)<150000,'OVERSIZE_MODULE')
 new,where=make_patch(old.decode('utf8'))
 mode=stat.S_IMODE(LIVE.stat().st_mode)
 require(not mode&0o022,'UNSAFE_PERMISSIONS')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=BACK/('news_rg_poll_moderation_v1.before_v6_'+stamp+'.py')
 fd=os.open(str(backup),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 with os.fdopen(fd,'wb') as f:f.write(old);f.flush();os.fsync(f.fileno())
 require(LIVE.read_bytes()==old,'CONCURRENT_EDIT_ABORT')
 try:
  atomic(LIVE,new.encode('utf8'),mode)
  require(sha(LIVE.read_bytes())==sha(new.encode('utf8')),'WRITE_CHECK_FAILED')
 except Exception:
  atomic(LIVE,old,mode)
  raise RuntimeError('ROLLED_BACK')
 return {'status':'RG_POLL_V6_SAFE_INSTALL_PASS','before_sha256':sha(old),'after_sha256':sha(LIVE.read_bytes()),
  'backup':str(backup),'lines':where,'generation_quality_gate':True,
  'approval_quality_gate':True,'approval_publication_paused':True,'photo_and_poll_send_prevented':True,
  'telegram_calls_during_install':0,'publications_during_install':0,'other_modules_changed':0}
def selftest():
 fixture="""def validate_poll(question,options,topic):
 if not question:raise ValueError('bad')
 return True
def make_variant(used,required_event=None):
 return None
def callback(update,cfg):
 action=update
 v={'question':'What question?','options':['one','two','three','four']}
 state={'publications':0}
 if action=='pub':
  if state.get('publications')!=0:return {'status':'POLL_ALREADY_PUBLISHED'}
  v['status']='PUBLIC_SEND_UNCERTAIN';state['current']='PUBLIC_SEND_UNCERTAIN'
 if action=='pub':
  image_id=send_photo(v)
  res=telegram('sendPoll',{})
 return None
"""
 amended,info=make_patch(fixture)
 require(amended.count(MARK)==2,'SELFTEST_COUNT')
 require(amended.index('POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL')<amended.index("v['status']='PUBLIC_SEND_UNCERTAIN'"),'SELFTEST_ORDER')
 print(json.dumps({'status':'RG_POLL_V6_OFFLINE_PASS','telegram_calls':0,'publications':0}))
if __name__=='__main__':
 try:print(json.dumps(selftest() if '--selftest' in sys.argv else apply(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_V6_SAFE_STOP','reason':str(e)[:180],'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
