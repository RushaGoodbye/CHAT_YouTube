#!/usr/bin/env python3
"""P24: READ-ONLY verify whether running rg-monitor can consume News2 callbacks.
No Telegram API calls; never print token values, URLs or source literals.
"""
import ast,datetime,json,os,pathlib,re,subprocess,sys
SOURCE=pathlib.Path('/volume1/docker/RG_MONITOR/app/main.py')
NEWS_TOKEN=pathlib.Path('/volume1/docker/RG_SECRETS/rg_telegram_bot_token')
DOCKER='/usr/local/bin/docker'
def run(cmd):
 try:
  p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=25)
  return p.returncode,p.stdout
 except Exception:return 99,''
def astpath(n):
 if isinstance(n,ast.Name):return n.id
 if isinstance(n,ast.Attribute):return astpath(n.value)+'.'+n.attr
 if isinstance(n,ast.Call):return astpath(n.func)+'(...)'
 return type(n).__name__
def inspect_source():
 src=SOURCE.read_text('utf-8',errors='replace')
 tree=ast.parse(src)
 defs=[x for x in ast.walk(tree) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))]
 fn=next((n for n in defs if n.name=='telegram_poll_loop'),None)
 if fn is None:return {'present':False}
 getcalls=[];fn_calls=[]
 for x in ast.walk(tree):
  if not isinstance(x,ast.Call):continue
  literal_keys=[v.value for v in x.args if isinstance(v,ast.Constant) and isinstance(v.value,str)]
  if 'getUpdates' in literal_keys:
   enclosing=[n for n in defs if n.lineno<=x.lineno<=getattr(n,'end_lineno',n.lineno)]
   enclosing.sort(key=lambda n:getattr(n,'end_lineno',n.lineno)-n.lineno)
   getcalls.append({'line':x.lineno,'in_function':enclosing[0].name if enclosing else '<module>',
     'call':astpath(x.func)[:100]})
  if astpath(x.func)=='telegram_poll_loop':
   parents=[n for n in defs if n.lineno<=x.lineno<=getattr(n,'end_lineno',n.lineno)]
   parents.sort(key=lambda n:getattr(n,'end_lineno',n.lineno)-n.lineno)
   fn_calls.append({'line':x.lineno,'in_function':parents[0].name if parents else '<module>'})
 decorator_sites=[]
 for n in defs:
  ds=[astpath(d.func) if isinstance(d,ast.Call) else astpath(d) for d in n.decorator_list]
  if any('startup' in d or 'lifespan' in d or 'on_event' in d for d in ds) or n.name in ('startup','lifespan','telegram_poll_loop'):
   decorator_sites.append({'name':n.name,'line':n.lineno,'decorators':ds[:6],'async':isinstance(n,ast.AsyncFunctionDef)})
 relevant_vars=[]
 for x in ast.walk(fn):
  if isinstance(x,ast.Call):
   f=astpath(x.func)
   if any(t in f for t in ('sleep','wait_for','create_task','getenv','environ.get','api','request','post','get')):
    relevant_vars.append({'line':x.lineno,'call':f[:90]})
 return {'present':True,'lines':[fn.lineno,getattr(fn,'end_lineno',fn.lineno)],
  'getupdates_calls':getcalls[:20],'telegram_poll_loop_call_sites':fn_calls[:20],
  'lifespan_or_startup_sites':decorator_sites[:25],
  'poll_loop_relevant_calls':relevant_vars[:35]}
def docker_inspect(name):
 rc,stdout=run([DOCKER,'inspect',name])
 if rc:return {'exists':False}
 try:
  raw=json.loads(stdout)[0]
  env=raw.get('Config',{}).get('Env') or []
  envmap={}
  for entry in env:
   if '=' not in entry:continue
   k,v=entry.split('=',1)
   envmap[k]=v
  secret=NEWS_TOKEN.read_text('utf-8').strip() if NEWS_TOKEN.is_file() else None
  keys=sorted(k for k in envmap if any(t in k.upper() for t in ('TOKEN','BOT','TELEGRAM','POLL')))
  compares=[]
  for k in keys:
   if 'TOKEN' not in k.upper():continue
   v=envmap[k]
   # Never reveal the secret nor any cryptographic digest of it.
   is_like=bool(re.fullmatch(r'\d{6,14}:[\w-]{20,}',v))
   if is_like:
    compares.append({'key':k,'matches_news2_secret':v==secret if secret else None})
  labels=raw.get('Config',{}).get('Labels') or {}
  state=raw.get('State',{})
  mounts=raw.get('Mounts') or []
  return {'exists':True,'running':state.get('Running'),
   'pid':state.get('Pid'),'image':raw.get('Config',{}).get('Image'),
   'service':labels.get('com.docker.compose.service'),
   'configured_env_key_names':keys,'candidate_bot_tokens':compares,
   'mount_destinations':[m.get('Destination') for m in mounts if any(t in str(m.get('Destination','')).lower() for t in ('secret','config','telegram','monitor'))][:12]}
 except Exception as e:return {'exists':True,'inspect_error_type':type(e).__name__}
def main():
 if os.geteuid()!=0 or not SOURCE.is_file():
  print(json.dumps({'status':'P24_BLOCKED','reason':'SUDO_OR_MONITOR_SOURCE_MISSING'}));sys.exit(1)
 output={'status':'NEWS2_P24_MONITOR_POLLER_READONLY','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'source':inspect_source(),
   'rg_monitor':docker_inspect('rg-monitor'),
   'rg_public_monitor':docker_inspect('rg-public-monitor'),
   'token_file_present':NEWS_TOKEN.is_file(),
   'publication_untouched':True,'getUpdates_calls':0,'channel_sends':0,'changes':0,
   'note':'A poll-loop in source does not prove which bot receives its updates.'}
 print(json.dumps(output,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
