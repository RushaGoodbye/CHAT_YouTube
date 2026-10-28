#!/usr/bin/env python3
"""NEWS RG production stability audit. Strictly read-only, zero AI/Telegram calls.

No poller, no scheduler, no bot token, no network, no DB writes, no publication.
Use this as a live NAS diagnostic; do not infer DSM origin from launch timestamps.
Exit status: 0 healthy/waiting, 1 warning, 2 critical, 3 insufficient evidence.
"""
import os,sys,json,time,pathlib,sqlite3,datetime,re,collections
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
EXPECTED_CHANNEL=-1001755891079
EXPECTED_BOT=7492268627
KEY_RE=re.compile(r'^[0-9a-f]{24}\.json$')
TAGS={
 'scan':'# NEWS_RG_ISOLATED_SCHEDULE_V2',
 'private':'# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1',
 'publish':'# NEWS_RG_APPROVED_PUBLICATION_CUTOVER_V1'
}
TARGETS={
 'scan':'news_rg_safe_schedule_v2.py',
 'private':'news_rg_private_dispatch_schedule_v1.py',
 'publish':'news_rg_publication_schedule_v1.py'
}
def read_json(p,max_bytes=32000):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>max_bytes:return None
  obj=json.loads(p.read_text(encoding='utf-8'))
  return obj if isinstance(obj,dict) else None
 except (ValueError,OSError,UnicodeError):return None
def age_minutes(stamp,now):
 try:
  v=float(stamp)
  if not 1700000000<v<now+3600:return None
  return round(max(0,(now-v)/60),1)
 except (TypeError,ValueError,OverflowError):return None
def marker(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>100:return None
  return float(p.read_text(encoding='utf-8').strip())
 except (OSError,ValueError,UnicodeError):return None
def flag(alerts,level,code,detail):
 alerts.append({'level':level,'code':code,'detail':detail})
def freshness(alerts,name,minutes,warn,critical,required=True):
 if minutes is None:
  if required:flag(alerts,'UNKNOWN',name+'_EVIDENCE_MISSING','Не найдено актуального временного маркера')
  return
 if minutes>=critical:
  flag(alerts,'CRITICAL',name+'_STALE',str(minutes)+' мин без подтверждённого обновления')
 elif minutes>=warn:
  flag(alerts,'WARNING',name+'_LATE',str(minutes)+' мин от последнего обновления')
def source_scan(now,alerts):
 p=OP/'news_rg_editorial_shadow_v1.sqlite3'
 if p.is_symlink() or not p.is_file():
  flag(alerts,'CRITICAL','SOURCE_DB_MISSING','Нет базы сбора новостей')
  return {'status':'MISSING'}
 try:
  db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=4)
  try:
   db.execute('pragma query_only=ON')
   tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
   if not {'source_cursor','story_shadow'}.issubset(tables):
    flag(alerts,'CRITICAL','SOURCE_DB_SCHEMA_CHANGED','Нужные таблицы не найдены')
    return {'status':'SCHEMA_CHANGED'}
   ccols={r[1] for r in db.execute('pragma table_info(source_cursor)')}
   scols={r[1] for r in db.execute('pragma table_info(story_shadow)')}
   if 'last_scan_at' not in ccols or 'posted_at' not in scols:
    flag(alerts,'CRITICAL','SOURCE_COLUMNS_CHANGED','Не найдены поля времени')
    return {'status':'SCHEMA_CHANGED'}
   total,scan=db.execute('select count(*),max(last_scan_at) from source_cursor').fetchone()
   stories,lastpost=db.execute('select count(*),max(posted_at) from story_shadow').fetchone()
   scanage=age_minutes(scan,now)
   freshness(alerts,'SOURCE_SCAN',scanage,90,180)
   if total<1:flag(alerts,'CRITICAL','SOURCES_EMPTY','В базе нет источников')
   return {'status':'OK','source_count':total,'story_count':stories,
    'last_scan_age_min':scanage,'newest_story_age_min':age_minutes(lastpost,now)}
  finally:db.close()
 except (sqlite3.Error,OSError,ValueError):
  flag(alerts,'CRITICAL','SOURCE_DB_READ_FAILED','База источников недоступна для чтения')
  return {'status':'READ_FAILED'}
def tick_wiring(alerts):
 script=BASE/'rg_news_dsm_tick.sh'
 if script.is_symlink() or not script.is_file():
  flag(alerts,'CRITICAL','DSM_TICK_FILE_MISSING','Скрипт штатного расписания отсутствует')
  return {'status':'MISSING'}
 try:
  if script.stat().st_size>80000:raise ValueError('oversize')
  body=script.read_text('utf-8')
 except (OSError,UnicodeError,ValueError):
  flag(alerts,'CRITICAL','DSM_TICK_READ_FAILED','Скрипт расписания не прочитан')
  return {'status':'UNREADABLE'}
 hooks={key:(body.count(tag)==1 and body.count(TARGETS[key])==1) for key,tag in TAGS.items()}
 for name,ok in hooks.items():
  if not ok:flag(alerts,'CRITICAL','DSM_HOOK_'+name.upper()+'_MISSING','Ожидаемый вызов не найден ровно один раз')
 # Only static evidence. A wired hook does not imply DSM is enabled or actually running.
 return {'status':'WIRED' if all(hooks.values()) else 'CHECK_REQUIRED','hooks':hooks,
  'origin_proven':'NO','enabled_proven':'NO'}
def private_queue(now,alerts):
 directory=OP/'news_rg_private_multipart_receipts_v1'
 decisions=OP/'news_rg_editorial_decisions_v1'
 if directory.is_symlink() or not directory.is_dir() or decisions.is_symlink() or not decisions.is_dir():
  flag(alerts,'CRITICAL','PRIVATE_LEDGER_MISSING','Журналы модерации отсутствуют')
  return {'status':'MISSING'},set(),False
 waiting=[];confirmed=0;newest=None;keys=set()
 all_files=list(directory.glob('*.json'))
 if len(all_files)>20000:
  flag(alerts,'CRITICAL','PRIVATE_LEDGER_TOO_LARGE','Слишком много карточек для безопасного аудита')
  return {'status':'OVERSIZE'},set(),False
 for p in all_files:
  if not KEY_RE.fullmatch(p.name):continue
  v=read_json(p)
  if not v:
   flag(alerts,'CRITICAL','PRIVATE_RECEIPT_INVALID','Некорректный журнал доставки')
   continue
  if v.get('status') in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY'):
   flag(alerts,'CRITICAL','PRIVATE_SEND_UNCERTAIN','Возможная отправка; повтор запрещён')
  if v.get('status')!='PRIVATE_SENT_CONFIRMED':continue
  if v.get('draft_id')!=p.stem or not isinstance(v.get('message_id'),int):
   flag(alerts,'CRITICAL','PRIVATE_RECEIPT_MISMATCH','Некорректная связь карточки')
   continue
  confirmed+=1;keys.add(p.stem)
  ts=v.get('confirmed_at')
  if isinstance(ts,(int,float)):newest=max(newest or 0,ts)
  dec=read_json(decisions/p.name)
  if dec is None:
   waiting.append({'message_id':v['message_id'],'age_min':age_minutes(ts,now)})
  elif dec.get('telegram_message_id')!=v.get('message_id') or dec.get('draft_id')!=p.stem:
   flag(alerts,'CRITICAL','EDITORIAL_DECISION_MISMATCH','Решение не соответствует отправленной карточке')
 # Human moderation is NOT a scheduler error, regardless of its age.
 waiting.sort(key=lambda x:x['message_id'],reverse=True)
 if len(waiting)>1:
  flag(alerts,'WARNING','MULTIPLE_REVIEW_CARDS_OUTSTANDING','Ожидается более одной карточки при лимите одной')
 return {'status':'OK','confirmed_private_cards':confirmed,
    'waiting_for_human_count':len(waiting),'pending_cards':waiting[:3],
    'latest_private_age_min':age_minutes(newest,now)},keys,bool(waiting)
def staging_pending(now,alerts,already_sent,waiting):
 folder=OP/'news_rg_private_review_staging'
 if folder.is_symlink() or not folder.is_dir():
  flag(alerts,'CRITICAL','STAGING_DIR_MISSING','Нет папки AI-черновиков')
  return {'status':'MISSING'}
 ready=[];count=0
 for p in folder.glob('*.json'):
  if count>=20000:
   flag(alerts,'WARNING','STAGING_TOO_LARGE','Аудит ограничен 20000 файлов')
   break
  count+=1
  if not KEY_RE.fullmatch(p.name) or p.stem in already_sent:continue
  v=read_json(p)
  if not v:continue
  if v.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1' or v.get('draft_id')!=p.stem:continue
  if v.get('telegram_delivery')!='NOT_SENT' or v.get('public_publication')!='OFF':continue
  if v.get('editorial_status')!='HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED':continue
  txt=v.get('proposed_text')
  if not isinstance(txt,str) or not 60<=len(txt)<=900:continue
  ready.append(age_minutes(v.get('prepared_at'),now))
 valid=[x for x in ready if x is not None]
 oldest=max(valid) if valid else None
 if ready and not waiting:
  freshness(alerts,'PRIVATE_READY_STAGING',oldest,35,90,required=False)
 return {'status':'OK','eligible_unsent_count':len(ready),
   'oldest_unsent_age_min':oldest,'pending_human_blocks_new_delivery':bool(waiting)}
def public_queue(now,alerts):
 activated=read_json(OP/'news_rg_publication_activation_v1.json')
 if activated is None or activated.get('status')!='ACTIVE' or activated.get('chat_id')!=EXPECTED_CHANNEL or activated.get('bot_id')!=EXPECTED_BOT:
  flag(alerts,'CRITICAL','PUBLICATION_GATE_NOT_ACTIVE','Публичная публикация выключена или изменена')
 activated_at=activated.get('activated_at') if activated else None
 decisions=OP/'news_rg_editorial_decisions_v1'
 pubs=OP/'news_rg_publication_receipts_v1'
 if decisions.is_symlink() or not decisions.is_dir() or pubs.is_symlink() or not pubs.is_dir():
  flag(alerts,'CRITICAL','PUBLICATION_LEDGER_MISSING','Нет журнала решений или публикаций')
  return {'status':'MISSING'}
 confirmed=0;uncertain=0;pending=[];last_pub=None;rows=0
 for receiptpath in pubs.glob('*.json'):
  rows+=1
  if rows>20000:
   flag(alerts,'CRITICAL','PUBLIC_RECEIPT_TOO_LARGE','Журнал публикаций превышает лимит аудита')
   break
  if not KEY_RE.fullmatch(receiptpath.name):continue
  r=read_json(receiptpath)
  if r is None:
   flag(alerts,'CRITICAL','PUBLIC_RECEIPT_UNREADABLE','Нечитаемая запись об отправке')
   continue
  if r.get('status')=='PUBLIC_SEND_UNCERTAIN_NO_RETRY':
   uncertain+=1
   flag(alerts,'CRITICAL','PUBLIC_SEND_UNCERTAIN_STOP','Не повторять отправку до ручной сверки Telegram')
  if r.get('status')=='PUBLIC_PUBLISHED_CONFIRMED':
   confirmed+=1
   if r.get('channel_id')!=EXPECTED_CHANNEL or not isinstance(r.get('message_id'),int):
    flag(alerts,'CRITICAL','PUBLIC_CHANNEL_RECEIPT_MISMATCH','Ответ Telegram не соответствует каналу')
   ts=r.get('published_at')
   if isinstance(ts,(int,float)):last_pub=max(last_pub or 0,ts)
 dcount=0
 for p in decisions.glob('*.json'):
  dcount+=1
  if dcount>20000:
   flag(alerts,'WARNING','DECISIONS_SCAN_LIMIT','Проверены не все решения')
   break
  if not KEY_RE.fullmatch(p.name):continue
  d=read_json(p)
  if not d or d.get('decision')!='editorially_accepted_not_published':continue
  t=d.get('timestamp')
  if not isinstance(t,int) or not isinstance(activated_at,int) or t<=activated_at:continue
  if (pubs/p.name).exists():continue
  minutes=age_minutes(t,now)
  if minutes is None:continue
  pending.append(minutes)
  if minutes>=35:
   flag(alerts,'CRITICAL','APPROVED_NOT_PUBLISHED','Одобренный пост ожидает '+str(minutes)+' мин')
  elif minutes>=15:
   flag(alerts,'WARNING','APPROVED_PUBLICATION_DELAY','Одобренный пост ожидает '+str(minutes)+' мин')
 return {'status':'OK','confirmed_publications':confirmed,'uncertain_sends':uncertain,
   'accepted_without_receipt':len(pending),
   'oldest_approved_unpublished_age_min':max(pending) if pending else None,
   'latest_publication_age_min':age_minutes(last_pub,now)}
def severity(alerts):
 types={x['level'] for x in alerts}
 if 'CRITICAL' in types:return 'CRITICAL',2
 if 'WARNING' in types:return 'WARNING',1
 if 'UNKNOWN' in types:return 'UNKNOWN',3
 return 'HEALTHY',0
def inspect():
 now=time.time()
 alerts=[]
 activation=read_json(OP/'news_rg_publication_activation_v1.json')
 aiage=age_minutes(marker(OP/'news_rg_last_launch_utc'),now)
 freshness(alerts,'AI_STAGE',aiage,90,150)
 source=source_scan(now,alerts)
 tick=tick_wiring(alerts)
 private,keys,waiting=private_queue(now,alerts)
 stage=staging_pending(now,alerts,keys,waiting)
 public=public_queue(now,alerts)
 state,rc=severity(alerts)
 return {
  'schema':'NEWS_RG_STABILITY_V1','checked_at_utc':datetime.datetime.fromtimestamp(now,datetime.timezone.utc).isoformat(),
  'status':state,'severity_exit_code':rc,
  'read_only':True,'ai_calls':0,'telegram_calls':0,'new_pollers':0,'db_writes':0,'publications_triggered':0,
  'production_configuration_changed':False,
  'source':source,'ai_stage_last_launch_age_min':aiage,'private':private,
  'staging':stage,'public':public,'dsm':tick,
  'public_gate_active':bool(activation and activation.get('status')=='ACTIVE'),
  'alerts':alerts,
  'normal_conditions':['Отсутствие свежих новостей при работающем сканере',
    'Одна карточка ожидает решения модератора','Нет новых публикаций без одобренных материалов'],
  'autonomy_evidence':'Журналы подтверждают работу модулей; источник запуска DSM не доказан только маркерами.'
 }
def selftest():
 checks=[]
 def chk(lv):checks.append({'level':lv})
 assert severity(checks)==('HEALTHY',0)
 chk('UNKNOWN');assert severity(checks)==('UNKNOWN',3)
 chk('WARNING');assert severity(checks)==('WARNING',1)
 chk('CRITICAL');assert severity(checks)==('CRITICAL',2)
 empty=[]
 freshness(empty,'SOURCE_SCAN',89,90,180)
 assert empty==[]
 freshness(empty,'SOURCE_SCAN',91,90,180)
 assert empty[0]['code']=='SOURCE_SCAN_LATE'
 empty=[]
 freshness(empty,'APPROVED_PUBLICATION',40,15,35)
 assert empty[0]['code']=='APPROVED_PUBLICATION_STALE'
 assert age_minutes(None,time.time()) is None
 assert age_minutes(time.time()-120,time.time()) is not None
 print('NEWS_RG_STABILITY_HEALTHCHECK_SELFTEST_PASS')
if __name__=='__main__':
 if sys.argv[1:]==['selftest']:selftest()
 elif sys.argv[1:]==['check']:
  try:
   result=inspect()
   print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
   sys.exit(result['severity_exit_code'])
  except Exception as ex:
   print(json.dumps({'status':'UNKNOWN','reason_class':type(ex).__name__,
     'read_only':True,'ai_calls':0,'telegram_calls':0,'db_writes':0,'publications_triggered':0},ensure_ascii=False))
   sys.exit(3)
 else:raise SystemExit('EXPECTED_SELFTEST_OR_CHECK')
