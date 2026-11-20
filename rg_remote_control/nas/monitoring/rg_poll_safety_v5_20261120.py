#!/usr/bin/env python3
"""RG NEWS2 poll V5: structural guard, no Telegram calls."""
import ast,datetime,hashlib,json,os,stat,sys,tempfile
from pathlib import Path
R=Path('/volume1/docker/RG_TELEGRAM_NEWS_2'); P=R/'operator/news_rg_poll_moderation_v1.py'
Q=R/'operator/news_rg_poll_quality_v1.py'; B=R/'rg_news2_fix_20261119/protected_backups'
QSHA='bc585371bc693093a5469ca7abc32a09a35a9ebdec67f919223c52a1c05b4e22'
MARK='RG_POLL_SAFETY_V5_FAIL_CLOSED'
def sha(b):return hashlib.sha256(b).hexdigest()
def guard(s):
 if MARK in s:raise ValueError('ALREADY_INSTALLED')
 tree=ast.parse(s)
 fs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
 if not all(k in fs for k in ('validate_poll','make_variant','callback')):raise ValueError('FUNCTIONS_CHANGED')
 v=fs['validate_poll']; cb=fs['callback']; code=ast.get_source_segment(s,cb) or ''
 if not all(k in (ast.get_source_segment(s,v) or '') for k in ('POLL_TOPIC_NOT_GROUNDED','POLL_OPTIONS_COUNT','POLL_GENERIC_OR_HEADLINE_LIST')):raise ValueError('VALIDATOR_CHANGED')
 if not all(k in code for k in ("action=='pub'","v['status']='PUBLIC_SEND_UNCERTAIN'",'send_photo','sendPoll','POLL_HUMAN_REVIEW_REQUIRED_NO_SEND')):raise ValueError('CALLBACK_CHANGED')
 if s.count('RG_POLL_EXPLICIT_REVIEW_REQUIRED_V3')!=1:raise ValueError('PREVIOUS_GUARD_MISSING')
 returns=[n for n in ast.walk(v) if isinstance(n,ast.Return) and isinstance(n.value,ast.Constant) and n.value.value is True]
 if len(returns)!=1 or v.body[-1] is not returns[0]:raise ValueError('VALIDATOR_RETURN_CHANGED')
 cl=sorted({n.lineno for n in ast.walk(cb) if isinstance(n,ast.Assign) and "v['status']='PUBLIC_SEND_UNCERTAIN';state['current']='PUBLIC_SEND_UNCERTAIN'" in s.splitlines()[n.lineno-1]})
 photos=[n for n in ast.walk(cb) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='send_photo']
 polls=[n for n in ast.walk(cb) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='telegram' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='sendPoll']
 if len(cl)!=1 or len(photos)!=1 or len(polls)!=1:raise ValueError('PUBLIC_CALL_COUNT_CHANGED')
 a=returns[0].lineno;b=cl[0];c=photos[0].lineno
 if not(a<b<c<polls[0].lineno):raise ValueError('PUBLIC_ORDER_CHANGED')
 lines=s.splitlines(keepends=True)
 if lines[a-1].strip()!='return True' or lines[b-1].strip()!="v['status']='PUBLIC_SEND_UNCERTAIN';state['current']='PUBLIC_SEND_UNCERTAIN'" or 'image_id=send_photo' not in lines[c-1].replace(' ',''):raise ValueError('SOURCE_ANCHORS_CHANGED')
 nl='\r\n' if '\r\n' in s else '\n'
 def indent(n):
  x=lines[n-1];z=x[:len(x)-len(x.lstrip(' \t'))]
  if not z or '\t' in z:raise ValueError('INDENT_CHANGED')
  return z
 x=indent(a);y=indent(b);z=indent(c)
 ins=[
 (a,x+'# '+MARK+nl+x+'from news_rg_poll_quality_v1 import validate as _poll_qa'+nl+x+'_poll_qa(question,options)'+nl),
 (b,y+'# '+MARK+nl+y+'try:'+nl+y+' from news_rg_poll_quality_v1 import validate as _poll_qa'+nl+y+" _poll_qa(v.get('question'),v.get('options'))"+nl+y+'except Exception:'+nl+y+" return {'status':'POLL_EDITORIAL_QA_FAILED_NO_PUBLICATION','publications':0}"+nl+y+"return {'status':'POLL_PUBLICATION_PAUSED_FOR_REVIEW','publications':0}"+nl),
 (c,z+'# '+MARK+nl+z+"raise RuntimeError('POLL_PUBLIC_MEDIA_SEND_DISABLED')"+nl)
 ]
 for n,txt in sorted(ins,reverse=True):lines.insert(n-1,txt)
 result=''.join(lines);ast.parse(result)
 if result.count(MARK)!=3:raise ValueError('GUARD_COUNT_INVALID')
 return result,{'qa_line':a,'decision_line':b,'photo_line':c}
def atomic(p,b,mode):
 fd,tmp=tempfile.mkstemp(prefix='.rg_poll_v5_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(p))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def main():
 if os.geteuid()!=0:raise ValueError('ROOT_REQUIRED')
 if any(x.is_symlink() or not x.is_dir() for x in (P.parent,B)):raise ValueError('DIR_UNSAFE')
 if any(x.is_symlink() or not x.is_file() for x in (P,Q)):raise ValueError('FILE_UNSAFE')
 if sha(Q.read_bytes())!=QSHA:raise ValueError('QUALITY_SHA_CHANGED')
 raw=P.read_bytes()
 if len(raw)>100000:raise ValueError('SOURCE_TOO_LARGE')
 edited,lines=guard(raw.decode('utf8'));new=edited.encode('utf8')
 mode=stat.S_IMODE(P.stat().st_mode)
 if mode&0o022:raise ValueError('FILE_PERMISSIONS_UNSAFE')
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=B/('news_rg_poll_moderation_v1.before_v5_'+stamp+'.py')
 fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
 with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 if P.read_bytes()!=raw:raise ValueError('CONCURRENT_CHANGE_NO_WRITE')
 try:
  atomic(P,new,mode)
  if sha(P.read_bytes())!=sha(new):raise RuntimeError('VERIFY_FAILED')
 except Exception:
  atomic(P,raw,mode);raise RuntimeError('ROLLED_BACK')
 return {'status':'RG_POLL_V5_INSTALLED_STAGED_OFF','before_sha256':sha(raw),'after_sha256':sha(new),
 'backup':str(backup),'anchors':lines,'quality_connected':True,'public_send_blocked':True,
 'telegram_calls':0,'publications':0,'other_modules_changed':0}
def selftest():
 s=("def validate_poll(question,options,topic):\n"
 " if len(options)!=4:raise RuntimeError('POLL_OPTIONS_COUNT')\n"
 " if not topic:raise RuntimeError('POLL_TOPIC_NOT_GROUNDED')\n"
 " if not question:raise RuntimeError('POLL_GENERIC_OR_HEADLINE_LIST')\n"
 " return True\n"
 "def make_variant(used,required_event=None):\n pass\n"
 "def callback(update,cfg):\n"
 " action=update\n v={'question':'q','options':[]}\n state={'publications':0}\n"
 " if action=='pub':\n"
 "  v['status']='PUBLIC_SEND_UNCERTAIN';state['current']='PUBLIC_SEND_UNCERTAIN'\n"
 " if action=='pub':\n"
 "  try:\n"
 "   image_id=send_photo(v)\n"
 "   # RG_POLL_EXPLICIT_REVIEW_REQUIRED_V3\n"
 "   raise RuntimeError('POLL_HUMAN_REVIEW_REQUIRED_NO_SEND')\n"
 "   res=telegram('sendPoll',{})\n"
 "  except Exception:pass\n")
 edited,pos=guard(s)
 assert edited.count(MARK)==3 and edited.index('POLL_PUBLIC_MEDIA_SEND_DISABLED')<edited.index('image_id=send_photo')
 print('RG_POLL_V5_SELFTEST_PASS TELEGRAM_CALLS_0')
if __name__=='__main__':
 try:
  if '--selftest' in sys.argv:selftest()
  else:print(json.dumps(main(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_V5_SAFE_STOP','reason':str(e)[:120],'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
