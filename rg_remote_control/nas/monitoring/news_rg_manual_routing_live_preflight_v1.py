#!/usr/bin/env python3
"""NEWS RG: exact live manual link update-route preflight. READ ONLY.

Checks the installed singleton worker's update intake and consumption path.
No Telegram API, getUpdates, new polling, sends, DB mutations or secrets.
Does not output source lines, text of any Telegram message, or credentials.
"""
import ast,json,os,pathlib,re,hashlib,sys,datetime,time
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
PATHS={'worker':OP/'rg_news2_p31_guarded_callback_once.py','owner':OP/'callback_v29.py',
       'moderation':BASE/'rg_moderation.py','dsm_tick':BASE/'rg_news_dsm_tick.sh'}
def get(path):
 if not path.is_file() or path.is_symlink() or path.stat().st_size>400000:
  raise RuntimeError('UNSAFE_OR_MISSING_'+path.name)
 return path.read_text(encoding='utf8')
def allowed(text):
 found=[]
 try:
  tree=ast.parse(text)
  for node in ast.walk(tree):
   if isinstance(node,ast.Dict):
    for k,v in zip(node.keys,node.values):
     if isinstance(k,ast.Constant) and k.value=='allowed_updates':
      vals=None
      if isinstance(v,(ast.List,ast.Tuple)) and all(isinstance(x,ast.Constant) and isinstance(x.value,str) for x in v.elts):
       vals=[x.value for x in v.elts]
      found.append(vals if vals is not None else 'DYNAMIC')
   if isinstance(node,ast.Call):
    for kw in node.keywords:
     if kw.arg=='allowed_updates':
      v=kw.value;vals=None
      if isinstance(v,(ast.List,ast.Tuple)) and all(isinstance(x,ast.Constant) and isinstance(x.value,str) for x in v.elts):
       vals=[x.value for x in v.elts]
      found.append(vals if vals is not None else 'DYNAMIC')
 except SyntaxError:return ['SYNTAX_INVALID']
 return found
def function_index(text):
 try:tree=ast.parse(text)
 except SyntaxError:return {'parse_ok':False}
 funcs={}
 for v in ast.walk(tree):
  if isinstance(v,(ast.FunctionDef,ast.AsyncFunctionDef)):
   src=ast.get_source_segment(text,v) or ''
   if len(src)>100000:continue
   funcs[v.name]={
    'line':v.lineno,
    'gets_updates':'getUpdates' in src,
    'has_allowed_updates':'allowed_updates' in src,
    'mentions_message':'message' in src,
    'mentions_callback':'callback_query' in src,
    'has_url_detection':('t.me/' in src or 'urlsplit(' in src or 'article_link(' in src),
    'allowed_update_types':allowed(src)}
 return {'parse_ok':True,
         'relevant_functions':{k:d for k,d in funcs.items() if
           d['gets_updates'] or d['has_allowed_updates'] or
           k in ('once','poll_once','process_callback','handle','intake','moderator','run')}}
def references(text):
 lines=text.splitlines()
 keys=('getUpdates','allowed_updates','for u in ups','for update in',
       'putoff(', 'process_callback(', 'callback_query', 'message',
       'off=max(', 'WORKER=', 'poll_once(')
 rows=[]
 for i,line in enumerate(lines):
  hits=[k for k in keys if k in line]
  if not hits:continue
  row={'line':i+1,'signals':hits}
  if 'allowed_updates' in hits:
   row['mentions_message_literal']=bool(re.search(r'["\']message["\']',line))
   row['mentions_callback_literal']=bool(re.search(r'["\']callback_query["\']',line))
  rows.append(row)
 return rows[:100]
def file_summary(name,text):
 fn=function_index(text)
 return {'source_hash_16':hashlib.sha256(text.encode()).hexdigest()[:16],
  'file':name,'lines':len(text.splitlines()),'functions':fn,
  'allowed_updates_literal_values':allowed(text),
  'source_route_signals':references(text),
  'has_ne1_route':('NEWS_RG_NE1_OWNER_ROUTE_V1' in text),
  'mentions_existing_manual_handler':'rg_telegram_nas_native_bot_v01' in text,
  'mentions_exclusive_callback_guard':'FOREIGN_CALLBACK_FAMILY_DETECTED' in text}
def inspect():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 result={'schema':'NEWS_RG_MANUAL_LIVE_ROUTE_PREFLIGHT_V1',
  'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'read_only':True,'telegram_api_calls':0,'getUpdates_calls':0,
  'new_pollers':0,'publications':0,'db_writes':0}
 for name,path in PATHS.items():
  src=get(path)
  if name=='dsm_tick':
   result[name]={
    'source_hash_16':hashlib.sha256(src.encode()).hexdigest()[:16],
    'mentions_callback_worker':'callback_v29.py' in src or 'rg_news2_p31_guarded_callback_once.py' in src,
    'mentions_manual_handler':'rg_telegram_nas_native_bot_v01' in src}
  else:result[name]=file_summary(name,src)
 return result
def selftest():
 s="def once():\n  d={'allowed_updates':['callback_query']}\n  for u in ups:\n   q=u.get('callback_query') or {}\n"
 assert allowed(s)==[['callback_query']]
 assert function_index(s)['relevant_functions']['once']['mentions_callback'] is True
 assert not function_index(s)['relevant_functions']['once']['mentions_message']
 assert references(s)[0]['signals']==['allowed_updates']
 print('NEWS_RG_MANUAL_LIVE_ROUTE_PREFLIGHT_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['inspect']:
   print(json.dumps(inspect(),ensure_ascii=False,sort_keys=True,indent=2))
  else:raise RuntimeError('EXPECTED_SELFTEST_OR_INSPECT')
 except Exception as exc:
  print(json.dumps({'status':'SAFE_STOP','error_type':type(exc).__name__,
   'read_only':True,'telegram_api_calls':0,'publications':0}))
  sys.exit(2)
