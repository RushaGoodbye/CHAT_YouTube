#!/usr/bin/env python3
"""NEWS RG: explain why no new private Telegram review card.

Read-only: NO Bot API, network, polling, shell execution, publication, AI model calls,
SQLite writes or changes to production. Do not reveal content, tokens or source IDs.
"""
import sys,os,json,time,sqlite3,pathlib,collections,urllib.parse,datetime
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=ROOT/'operator'
DB=O/'news_rg_editorial_shadow_v1.sqlite3'
NOW=time.time()
def age(ts):
 try:
  v=float(ts)
  if v>NOW+3600 or v<1000000000:return None
  return round(max(0,NOW-v)/60,1)
 except (ValueError,TypeError,OverflowError):return None
def filemeta(p):
 try:
  if p.is_symlink() or not p.is_file():return {'present':False}
  return {'present':True,'age_minutes':round(max(0,NOW-p.stat().st_mtime)/60,1),
   'bytes':p.stat().st_size}
 except OSError:return {'present':False}
def marker(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>100:return None
  return age(float(p.read_text('utf8').strip()))
 except (ValueError,OSError):return None
def statusjson(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>5000:return None
  value=json.loads(p.read_text('utf8'))
  return {k:value.get(k) for k in ('status','reason') if k in value}
 except (ValueError,OSError):return None
def inventory():
 out={'schema':'NEWS_RG_NO_CARD_ROOT_CAUSE_V1','read_only':True,'nas_clock_utc':
  datetime.datetime.fromtimestamp(NOW,datetime.timezone.utc).isoformat(),
  'telegram_calls':0,'ai_calls':0,'network_calls':0,'db_writes':0,'publications':0}
 out['scheduler']={
  'last_ai_stage_launch_age_minutes':marker(O/'news_rg_last_launch_utc'),
  'last_private_dispatch_launch_age_minutes':marker(O/'news_rg_private_dispatch_last_launch'),
  'last_publication_launch_age_minutes':marker(O/'news_rg_publication_last_launch'),
  'ai_autorun_log':filemeta(O/'news_rg_autorun.log'),
  'private_autorun_log':filemeta(O/'news_rg_private_dispatch_autorun.log'),
  'publication_autorun_log':filemeta(O/'news_rg_publication_autorun.log'),
  'dispatch_last_state':statusjson(O/'news_rg_private_dispatch_status_v1.json'),
  'public_activation':(lambda x: {'status':x.get('status'),'activated_at_age_minutes':age(x.get('activated_at'))} if isinstance(x,dict) else {'status':'UNAVAILABLE'})(statusjson(O/'news_rg_publication_activation_v1.json'))}
 out['pipeline_files']={p:filemeta(O/p) for p in (
   'news_rg_final_tick_v1.py','news_rg_source_shadow_ingest_v1.py',
   'news_rg_private_bridge_v1.py','news_rg_ollama_adapter_v1.py',
   'news_rg_durable_private_dispatch_v1.py','news_rg_durable_private_sender_v1.py')}
 out['shadow']=shadow()
 out['staging']=staging()
 out['rejection_ledger']=rejections()
 out['reason_class']=reason(out)
 return out
def shadow():
 result={'status':'UNKNOWN'}
 if DB.is_symlink() or not DB.is_file():return {'status':'SHADOW_DB_MISSING'}
 try:
  con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=5)
  con.execute('pragma query_only=ON')
  try:
   tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
   if 'story_shadow' not in tables:return {'status':'SHADOW_TABLE_MISSING'}
   cols={r[1] for r in con.execute('pragma table_info(story_shadow)')}
   want={'status','posted_at','text','media_url'}
   if not want.issubset(cols):return {'status':'STORY_COLUMNS_CHANGED'}
   result={'status':'OK'}
   stat=con.execute("select status,count(*),max(posted_at) from story_shadow group by status").fetchall()
   result['statuses']=[{'status':str(k)[:50],'count':n,'latest_post_age_minutes':age(ts)} for k,n,ts in stat]
   result['newest_source_post_age_minutes']=age(max((r[2] or 0 for r in stat),default=0))
   eligible=con.execute("""select text,media_url,posted_at from story_shadow
     where status='needs_editorial_rewrite' order by posted_at desc limit 1000""").fetchall()
   result['rewrite_queue_inspected']=len(eligible)
   reasons=collections.Counter();recent=0;qualifying=0
   for content,media,posted in eligible:
    if age(posted) is not None and age(posted)<=240:recent+=1
    if len(content or '')<100:reasons['TEXT_UNDER_100']+=1;continue
    if not isinstance(media,str):reasons['NO_MEDIA_URL']+=1;continue
    u=urllib.parse.urlsplit(media)
    if u.scheme!='https' or u.hostname not in ('cdn1.telesco.pe','cdn2.telesco.pe',
      'cdn3.telesco.pe','cdn4.telesco.pe','cdn5.telesco.pe'):
     reasons['PHOTO_HOST_NOT_ALLOWED']+=1;continue
    qualifying+=1
   result['recent_rewrite_candidates_last_4h']=recent
   result['photo_and_length_qualified_count']=qualifying
   result['exclusion_counts']=dict(reasons)
   if 'source_cursor' in tables:
    ccols={r[1] for r in con.execute('pragma table_info(source_cursor)')}
    if 'last_scan_at' in ccols:
     x=con.execute('select count(*),max(last_scan_at) from source_cursor').fetchone()
     result['source_cursor_count']=x[0]
     result['latest_source_scan_age_minutes']=age(x[1])
  finally:con.close()
 except (OSError,sqlite3.Error,ValueError) as e:result={'status':'SHADOW_READ_ERROR','error_class':type(e).__name__}
 return result
def staging():
 directory=O/'news_rg_private_review_staging'
 if not directory.is_dir() or directory.is_symlink():return {'status':'STAGING_DIR_MISSING'}
 private=O/'news_rg_private_multipart_receipts_v1'
 old=O/'news_rg_private_delivery_v2'
 legacy=O/'news_rg_private_pilot_claim_v1.json'
 blocked={p.stem for d in (private,old) if d.is_dir() for p in d.glob('*.json')}
 if legacy.is_file() and not legacy.is_symlink() and legacy.stat().st_size<2000:
  try:blocked.add(json.loads(legacy.read_text('utf8')).get('draft_id'))
  except (ValueError,OSError):pass
 stats=collections.Counter();latest=None
 files=list(directory.glob('*.json'))
 if len(files)>10000:return {'status':'STAGING_TOO_LARGE','files':len(files)}
 for p in files:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>20000:stats['UNSAFE_JSON']+=1;continue
  try:obj=json.loads(p.read_text('utf8'))
  except (ValueError,OSError):stats['UNREADABLE']+=1;continue
  key=obj.get('draft_id')
  latest=max(latest or 0,p.stat().st_mtime)
  if key in blocked:stats['ALREADY_SENT_OR_RESERVED']+=1;continue
  if obj.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1':stats['BAD_SCHEMA']+=1;continue
  if obj.get('telegram_delivery')!='NOT_SENT':stats['NOT_UNSENT']+=1;continue
  if obj.get('public_publication')!='OFF':stats['PUBLIC_GUARD_CHANGED']+=1;continue
  if obj.get('editorial_status')!='HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED':
   stats['NOT_REVIEWABLE']+=1;continue
  txt=str(obj.get('proposed_text',''))
  if not 60<=len(txt)<=900 or 'НЕВДАЛО' in txt.upper() or any(c in txt for c in 'ыъэёЫЪЭЁ'):
   stats['TEXT_POLICY']+=1;continue
  stats['READY_FOR_PRIVATE_SEND']+=1
 return {'status':'OK','total_staged_files':len(files),'latest_stage_age_minutes':age(latest),
  'classifications':dict(stats),'ready_for_private_send':stats['READY_FOR_PRIVATE_SEND']}
def rejections():
 p=O/'news_rg_draft_rejections_v1.jsonl'
 if p.is_symlink() or not p.is_file():return {'present':False}
 if p.stat().st_size>2000000:return {'present':True,'too_large':True}
 reasons=collections.Counter();recent=0;total=0
 try:
  with p.open('r',encoding='utf8') as f:
   for line in f:
    total+=1
    try:
     d=json.loads(line)
     reason=str(d.get('reason','UNKNOWN'))
     if reason not in ('BAD_DRAFT','UNTRUSTED_MEDIA_HOST','NOT_PHOTO',
      'REJECTED_INSUFFICIENT_FACTS','REJECTED_MODEL_UNCERTAIN','REJECTED_ATTRIBUTION_LOSS'):
      reason='OTHER_REJECTION'
     reasons[reason]+=1
     if age(d.get('at')) is not None and age(d.get('at'))<=240:recent+=1
    except ValueError:reasons['INVALID_LINE']+=1
  return {'present':True,'total':total,'last_4h_count':recent,'reason_counts':dict(reasons)}
 except OSError:return {'present':True,'read_error':True}
def reason(d):
 s=d['shadow']; st=d['staging'];q=d['scheduler']
 if st.get('ready_for_private_send',0)>0:
  return 'STAGED_READY_BUT_NO_PRIVATE_CARD__CHECK_DISPATCH_STATUS'
 if s.get('status')!='OK':return 'SOURCE_SHADOW_UNAVAILABLE_OR_CHANGED'
 if q['last_ai_stage_launch_age_minutes'] is None:return 'AI_STAGING_LAUNCH_NOT_OBSERVED'
 if s.get('latest_source_scan_age_minutes') is not None and s['latest_source_scan_age_minutes']>120:
  return 'SOURCE_SCAN_STALE'
 if s.get('photo_and_length_qualified_count',0)==0:
  return 'NO_SOURCE_WITH_VALID_TEXT_AND_PHOTO'
 if st.get('total_staged_files',0)==0:return 'SOURCE_ELIGIBLE_BUT_AI_DRAFT_NOT_STAGED'
 if q.get('dispatch_last_state',{}):
  value=q['dispatch_last_state'].get('status')
  if value=='PAUSED':return 'PRIVATE_DISPATCH_PAUSED'
  if value=='NO_ELIGIBLE_DRAFT':return 'ALL_STAGED_DRAFTS_RESERVED_OR_INVALID'
 return 'NEED_TARGETED_AI_PREPARE_LOG'
if __name__=='__main__':
 if sys.argv[1:]==['selftest']:
  assert age(NOW-120) is not None
  assert age(None) is None
  assert reason({'shadow':{'status':'OK'},'staging':{'ready_for_private_send':1},'scheduler':{}})=='STAGED_READY_BUT_NO_PRIVATE_CARD__CHECK_DISPATCH_STATUS'
  print('NEWS_RG_NO_CARD_ROOT_CAUSE_SELFTEST_PASS')
 elif sys.argv[1:]==['check']:
  if os.geteuid()!=0:raise SystemExit('SUDO_REQUIRED')
  print(json.dumps(inventory(),ensure_ascii=False,indent=2,sort_keys=True))
 else:raise SystemExit('MODE: selftest|check')
