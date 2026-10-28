#!/usr/bin/env python3
"""NEWS RG manual Telegram news-link regression audit, strictly read-only.

NO Telegram API, getUpdates, bot credentials, new poller, network,
sqlite writes, message sends, DSM changes, or production imports.
Never outputs news texts, source URLs, user IDs, tokens, or private messages.
"""
import ast,collections,datetime,json,os,pathlib,re,sqlite3,sys,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
N=pathlib.Path('/volume1/docker/RG_TELEGRAM_STATE')
STATIC={
 'active_moderation':B/'rg_moderation.py',
 'update_owner':O/'callback_v29.py',
 'update_worker':O/'rg_news2_p31_guarded_callback_once.py',
 'legacy_manual_bot':N/'rg_telegram_nas_native_bot_v01.py',
 'dsm_tick':B/'rg_news_dsm_tick.sh'}
LINK=re.compile(r'(?i)https?://(?:t\.me|telegram\.me)/\S+')
def valid(p,size=450000):
 try:return not p.is_symlink() and p.is_file() and p.stat().st_size<=size
 except OSError:return False
def age(p):
 try:return round((time.time()-p.stat().st_mtime)/60,1)
 except OSError:return None
def summary(path):
 if not valid(path):return {'present':False}
 try:text=path.read_text('utf8')
 except (OSError,UnicodeError):return {'present':True,'readable':False}
 function_names=[]
 if path.suffix=='.py':
  try:
   tree=ast.parse(text)
   function_names=[x.name for x in ast.walk(tree)
         if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))]
  except SyntaxError:
   return {'present':True,'readable':True,'python_syntax_valid':False}
 # Expose boolean structural signals only; no source excerpts.
 return {'present':True,'readable':True,'age_min':age(path),
  'functions_relevant':[x for x in function_names if re.search(r'intake|message|source|link|handle|update|callback|forward|once|poll',x,re.I)][:35],
  'has_manual_url_parser':bool('article_link(' in text or 'urlsplit(' in text and 't.me' in text),
  'has_manual_intake_function':bool(re.search(r'(?m)^\s*def\s+(?:intake|process_message|handle_message|handle_incoming_message)\s*\(',text)),
  'has_message_update_branch':bool(re.search(r'(?:\.get\(|\[)\s*["\']message["\']',text)),
  'has_callback_update_branch':'callback_query' in text,
  'has_telegram_getupdates_reference':'getUpdates' in text,
  'has_editorial_ne1_hook':'NEWS_RG_EDITORIAL_HOOK_V1' in text or 'NEWS_RG_NE1_OWNER_ROUTE_V1' in text,
  'has_prior_manual_bot_dependency':'rg_telegram_nas_native_bot_v01' in text,
  'has_old_native_intake_call':bool(re.search(r'\bintake\s*\(',text) and 'message' in text),
  'dsm_refers_to_legacy_bot':'rg_telegram_nas_native_bot_v01.py' in text,
  'dsm_refers_to_callback_owner':'callback_v29.py' in text,
  'file_hash_prefix':__import__('hashlib').sha256(text.encode()).hexdigest()[:14]}
def db_status(path):
 if not valid(path,2500000000):return {'present':False}
 try:
  with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
   db.execute('pragma query_only=ON')
   tables={v[0] for v in db.execute("select name from sqlite_master where type='table'")}
   result={'present':True,'tables_of_interest':sorted(tables.intersection(
      {'bot_posts','bot_updates','bot_state','moderation_meta','candidates','updates','processed_updates',
       'news_submissions','manual_submissions','manual_links','incoming_links'}))}
   if 'bot_posts' in tables:
    cols={v[1] for v in db.execute('pragma table_info(bot_posts)')}
    if {'source_kind','status'}.issubset(cols):
     result['bot_posts_by_kind_status']=[
       {'kind':str(k)[:40],'status':str(st)[:40],'count':n}
       for k,st,n in db.execute('select source_kind,status,count(*) from bot_posts group by source_kind,status limit 25')]
    if 'created_at' in cols:
     newest=db.execute('select max(created_at) from bot_posts').fetchone()[0]
     result['bot_posts_latest_age_min']=round((time.time()-newest)/60,1) if isinstance(newest,(int,float)) else None
   if 'bot_updates' in tables:
    cols={v[1] for v in db.execute('pragma table_info(bot_updates)')}
    if 'processed_at' in cols:
     v=db.execute('select count(*),max(processed_at) from bot_updates').fetchone()
     result['bot_updates_count']=v[0]
     result['bot_updates_last_age_min']=round((time.time()-v[1])/60,1) if isinstance(v[1],(int,float)) else None
   if 'moderation_meta' in tables:
    cols={v[1] for v in db.execute('pragma table_info(moderation_meta)')}
    if 'key' in cols and 'value' in cols:
     result['moderation_offset_recorded']=db.execute("select 1 from moderation_meta where key='offset'").fetchone() is not None
   return result
 except (OSError,sqlite3.Error,ValueError):
  return {'present':True,'readable':False}
def archives():
 examined=0;updates=0;callbacks=0;messages=0;manual_like=0
 seen=set()
 if not O.is_dir() or O.is_symlink():return {'available':False}
 try:files=sorted(O.glob('*updates*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:65]
 except OSError:files=[]
 for p in files:
  if not valid(p,2000000):continue
  try:blob=json.loads(p.read_text(encoding='utf8'))
  except (OSError,ValueError,UnicodeError):continue
  if not isinstance(blob,dict) or not isinstance(blob.get('updates'),list):continue
  examined+=1
  for x in blob['updates'][:200]:
   if not isinstance(x,dict) or not isinstance(x.get('update_id'),int):continue
   uid=x['update_id']
   if uid in seen:continue
   seen.add(uid);updates+=1
   if x.get('callback_query'):callbacks+=1
   msg=x.get('message')
   if isinstance(msg,dict):
    messages+=1
    if LINK.search(str(msg.get('text') or msg.get('caption') or '')):manual_like+=1
 return {'archive_files_checked':examined,'unique_update_ids':updates,
  'callback_updates':callbacks,'message_updates':messages,
  'telegram_link_messages_found':manual_like,
  'note':'Archives can omit some updates; zero is not proof no messages arrived.'}
def logs():
 out={}
 for name in ('callback_v29.log','outbound_tick.log','native_bot.log'):
  p=O/name if name!='native_bot.log' else N/name
  if not valid(p,60000000):
   out[name]={'present':False};continue
  try:
   with p.open('rb') as h:
    h.seek(max(0,p.stat().st_size-100000))
    raw=h.read().decode('utf8','replace')
   words=('BOT_POLL_COMPLETED','ONE_SHOT_CALLBACK_HANDOFF_COMPLETE','FOREIGN_CALLBACK_FAMILY',
          'UPDATE_TYPE_MESSAGE','MANUAL_LINK','needs_forward','TELEGRAM_409_POLL_CONFLICT',
          'SAFE_STOP','ERROR')
   out[name]={'present':True,'age_min':age(p),
    'marker_counts':{w:raw.count(w) for w in words if raw.count(w)>0}}
  except OSError:out[name]={'present':True,'readable':False}
 return out
def report():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 result={
 'schema':'NEWS_RG_MANUAL_LINK_REGRESSION_READONLY_V1',
 'read_only':True,'telegram_api_calls':0,'getUpdates_calls':0,'db_writes':0,
 'new_pollers':0,'publications':0,'configuration_changes':0,
 'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'components':{name:summary(p) for name,p in STATIC.items()},
 'databases':{'active_news':db_status(B/'news.sqlite3'),
              'previous_manual_bot':db_status(N/'nas_native_bot.sqlite3')},
 'update_archives':archives(),'logs':logs()}
 active=result['components']['active_moderation']
 worker=result['components']['update_worker']
 native=result['components']['legacy_manual_bot']
 if (native.get('has_manual_intake_function') and native.get('has_manual_url_parser') and
     not active.get('has_manual_intake_function') and
     not worker.get('has_manual_intake_function')):
  result['diagnosis']='POSSIBLE_MANUAL_INTAKE_NOT_ROUTED_TO_ACTIVE_BOT'
 elif not native.get('present'):result['diagnosis']='LEGACY_MANUAL_HANDLER_NOT_FOUND'
 elif not worker.get('present'):result['diagnosis']='CURRENT_UPDATE_WORKER_MISSING'
 else:result['diagnosis']='NEEDS_LIVE_ROUTING_REVIEW'
 result['safe_next_step']='Repair ONLY active single-owner message routing, after identifying message update behavior. Never start old native bot poller.'
 return result
def selftest():
 assert LINK.search('https://t.me/abc_news/123')
 assert LINK.search('https://telegram.me/someNews/47')
 assert not LINK.search('https://example.com/')
 assert not valid(pathlib.Path('/does-not-exist-newsrg'))
 assert 'getUpdates' not in report.__code__.co_names
 print('NEWS_RG_MANUAL_LINK_REGRESSION_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['inspect']:print(json.dumps(report(),ensure_ascii=False,indent=2,sort_keys=True))
  else:raise RuntimeError('EXPECTED_SELFTEST_OR_INSPECT')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason_class':type(e).__name__,
   'telegram_api_calls':0,'new_pollers':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
