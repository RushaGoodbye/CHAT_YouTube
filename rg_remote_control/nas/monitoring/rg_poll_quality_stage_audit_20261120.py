#!/usr/bin/env python3
"""RG NEWS2: stage pure poll QA and audit existing moderation path, safely.
No Telegram, public posts, cron changes, poll activation or network calls.
"""
import ast,datetime,hashlib,json,os,pathlib,re,stat,subprocess,sys,tempfile
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=R/'operator';S=R/'rg_news2_fix_20261119';B=S/'protected_backups'
LIVE=O/'news_rg_poll_moderation_v1.py'
DST=O/'news_rg_poll_quality_v1.py'
STAGE=S/'news_rg_poll_quality_v1.py'
EXPECTED_LIVE_SHA='abcf4683e9e4629434471acf1c2813100d33febb323b6d9870e325f6c882d782'
def sha(data):return hashlib.sha256(data).hexdigest()
def atomic(path,data,mode):
 fd,name=tempfile.mkstemp(prefix='.poll_quality_',dir=str(path.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(name,str(path))
 finally:
  if os.path.exists(name):os.unlink(name)
def name_of(n):
 if isinstance(n,ast.Name):return n.id
 if isinstance(n,ast.Attribute):return name_of(n.value)+'.'+n.attr
 return type(n).__name__
def call_shape(n):
 return {'name':name_of(n.func),'argc':len(n.args),'kwargs':[x.arg for x in n.keywords if x.arg]}
def audit(code):
 tree=ast.parse(code)
 funcs=[x for x in tree.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))]
 callbacks=[f for f in funcs if f.name=='callback']
 relevant=[]
 def walk(f):
  for x in ast.walk(f):
   if isinstance(x,ast.Call):
    fn=name_of(x.func)
    if any(w in fn.casefold() for w in ('telegram','poll','persist','decis','approve','state','review','moder')):
     relevant.append({'line':x.lineno,**call_shape(x)})
 for f in funcs:
  if any(key in f.name for key in ('poll','callback','approv','review','draft','build','moder')):
   walk(f)
 sends=[]
 for n in ast.walk(tree):
  if isinstance(n,ast.Call) and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='sendPoll':
   sends.append({'line':n.lineno,'call':call_shape(n)})
 gates=[]
 for n in ast.walk(tree):
  if isinstance(n,ast.Raise) and n.exc and isinstance(n.exc,ast.Call) and n.exc.args:
   arg=n.exc.args[0]
   if isinstance(arg,ast.Constant) and arg.value=='POLL_HUMAN_REVIEW_REQUIRED_NO_SEND':
    gates.append(n.lineno)
 cb=callbacks[0] if len(callbacks)==1 else None
 cbinfo={}
 if cb:
  cbinfo={'line':cb.lineno,'end_line':cb.end_lineno,'parameters':[a.arg for a in cb.args.args],
   'branches':[{'line':x.lineno,'test_shape':type(x.test).__name__,
    'names':sorted({y.id for y in ast.walk(x.test) if isinstance(y,ast.Name)})[:10]}
    for x in ast.walk(cb) if isinstance(x,ast.If)][:20]}
 return {'functions':[{'name':f.name,'line':f.lineno,'argc':len(f.args.args)} for f in funcs],
  'callback':cbinfo,'sendPoll_calls':sends,'sendPoll_blocking_gates':gates,
  'relevant_calls':relevant[:60]}
def run():
 if os.geteuid()!=0:raise ValueError('ROOT_REQUIRED')
 for p in (O,S,B):
  if not p.is_dir() or p.is_symlink():raise ValueError('UNSAFE_DIRECTORY')
 for p in (LIVE,STAGE):
  if p.is_symlink() or not p.is_file():raise ValueError('UNSAFE_SOURCE')
 live=LIVE.read_bytes()
 if sha(live)!=EXPECTED_LIVE_SHA:raise ValueError('LIVE_POLL_CHANGED_SAFE_STOP')
 if len(live)>100000:raise ValueError('POLL_SOURCE_TOO_LARGE')
 src=STAGE.read_bytes()
 if len(src)>50000:raise ValueError('QUALITY_SOURCE_TOO_LARGE')
 ast.parse(src.decode('utf8'))
 if not all(x in src for x in (b'def validate(',b'def bank(',b'publication_authorized')):
  raise ValueError('QUALITY_SOURCE_INVALID')
 test=subprocess.run([sys.executable,'-B',str(STAGE)],capture_output=True,text=True,timeout=15)
 if test.returncode or 'RG_POLL_QUALITY_V1_OFFLINE_PASS' not in test.stdout:
  raise ValueError('QUALITY_TEST_FAILED')
 state='ALREADY_STAGED'
 if DST.exists():
  if DST.is_symlink() or sha(DST.read_bytes())!=sha(src):
   raise ValueError('EXISTING_QUALITY_MODULE_DIFFERENT_SAFE_STOP')
 else:
  atomic(DST,src,0o600)
  state='STAGED'
 if sha(DST.read_bytes())!=sha(src):raise ValueError('STAGE_VERIFY_FAILED')
 summary=audit(live.decode('utf8'))
 return {'status':'RG_POLL_QUALITY_AND_CONTRACT_AUDIT_PASS',
   'quality_module':state,'quality_sha256':sha(src),'live_poll_sha256':sha(live),
   'automatic_poll_publication_still_blocked':True,
   'next_step':'Connect explicit native moderator decision to checked poll receipt',
   'telegram_calls':0,'publications':0,'second_pollers':0,'contract':summary}
def selftest():
 stub=("def callback(update,telegram):\n"
       "  if update:\n"
       "    raise RuntimeError('POLL_HUMAN_REVIEW_REQUIRED_NO_SEND')\n"
       "    res=telegram('sendPoll',{'chat_id':100})\n"
       "  return 0\n")
 r=audit(stub)
 assert len(r['sendPoll_calls'])==1 and len(r['sendPoll_blocking_gates'])==1
 print(json.dumps({'status':'RG_POLL_CONTRACT_AUDIT_SELFTEST_PASS','telegram_calls':0,'publications':0}))
if __name__=='__main__':
 try:print(json.dumps(selftest() if '--selftest' in sys.argv else run(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_CONTRACT_AUDIT_SAFE_STOP','reason':str(e)[:120],
                    'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
