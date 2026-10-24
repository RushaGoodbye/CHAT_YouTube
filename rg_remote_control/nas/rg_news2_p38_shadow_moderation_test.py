#!/usr/bin/env python3
"""P38 News2 shadow moderation simulation: exercise actual NAS moderation code in a
separate temporary SQLite snapshot, with ALL Telegram API calls forbidden.
Reads a proven archived callback; never modifies production DB, cron, bot, or channel.
"""
import copy,datetime,json,os,pathlib,sqlite3,sys,tempfile
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
ARCHIVE=O/'updates_handoff_20261015T175210096025Z.json'
LIVE_DB=B/'news.sqlite3'
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
BOT_ID=7492268627
def emit(**o):print(json.dumps(o,ensure_ascii=False,sort_keys=True,indent=2),flush=True)
def fail(s):raise RuntimeError(s)
def archived_update():
 if not ARCHIVE.is_file() or ARCHIVE.is_symlink():fail('KNOWN_ARCHIVE_MISSING')
 payload=json.loads(ARCHIVE.read_text('utf-8'))
 matches=[]
 for u in payload.get('updates',[]):
  q=u.get('callback_query')
  if not isinstance(q,dict):continue
  msg=q.get('message') or {}
  user=q.get('from') or {}
  if (u.get('update_id')==615861392 and msg.get('message_id')==8018
      and str(q.get('data','')).startswith('rg3:recheck:')
      and (msg.get('from') or {}).get('username')=='RushaGoodbyeNews_bot'
      and user.get('is_bot') is False and
      (msg.get('chat') or {}).get('type')=='private'):
   matches.append(u)
 if len(matches)!=1:fail('REAL_RECHECK_ARCHIVE_NOT_AUTHENTICATED')
 return matches[0]
def open_shadow(path):
 c=sqlite3.connect(str(path),timeout=10)
 c.row_factory=sqlite3.Row
 return c
def scenario(name,source,m,cfg,old_db_connect,base):
 with tempfile.TemporaryDirectory(prefix='rg_news2_shadow_') as tmp:
  local=pathlib.Path(tmp)/'shadow.sqlite3'
  with sqlite3.connect('file:'+str(base)+'?mode=ro',uri=True,timeout=10) as production:
   with open_shadow(local) as shadow:production.backup(shadow)
  with open_shadow(local) as db:
   row=db.execute("""SELECT c.id,c.status FROM moderation_dispatch d
    JOIN candidates c ON c.id=d.candidate_id
    WHERE d.message_id=? LIMIT 1""",(8018,)).fetchone()
   if not row:return {'scenario':name,'result':'FAIL','reason':'NO_CARD_8018_IN_SNAPSHOT'}
   cid=row['id']
   prior=row['status']
   if prior!='needs_recheck':
    return {'scenario':name,'result':'BLOCKED','reason':'LIVE_RECHECK_STATUS_HAS_CHANGED',
     'actual_status':prior}
   db.execute("UPDATE candidates SET status=? WHERE id=?",
    ('awaiting_photo_review',cid))
   db.commit()
  test=copy.deepcopy(source)
  q=test['callback_query']
  q['data']='rg3:'+name+':'+str(q['data']).split(':',2)[2]
  # db_connect() is the only DB access function called by process_callback
  # per the P33 AST audit. Redirect to a private SQLite clone.
  def tempconnect():return open_shadow(local)
  api_calls=[]
  def block_api(method,payload):
   api_calls.append(str(method)[:35])
   fail('TELEGRAM_API_FORBIDDEN_IN_SHADOW_TEST')
  m.db_connect=tempconnect
  m.api=block_api
  try:
   try:r=m.process_callback(test,cfg)
   except Exception as exc:
    return {'scenario':name,'result':'FAIL','error_type':type(exc).__name__,
      'api_calls_attempted':len(api_calls)}
   with open_shadow(local) as db:
    result=db.execute("SELECT status FROM candidates WHERE id=?",(cid,)).fetchone()
    after=result[0] if result else None
   changed=(after is not None and after!='awaiting_photo_review')
   expected=after=='needs_recheck' if name=='recheck' else after not in ('awaiting_photo_review','awaiting_moderation','needs_recheck',None)
   return {'scenario':name,'result':'PASS' if changed and expected and not api_calls else 'FAIL',
    'before':'awaiting_photo_review','after':after,
    'state_changed':changed,'expected_transition':expected,
    'handler_result_status':str(r.get('status','UNKNOWN'))[:120] if isinstance(r,dict) else type(r).__name__,
    'api_calls_attempted':len(api_calls)}
  finally:
   m.db_connect=old_db_connect
def main():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 if LEG.exists() or LEG.is_symlink():fail('LEGACY_BOT_GATE_OPEN')
 if (B/'PUBLISH_ENABLED').exists():fail('PUBLICATION_GATE_MUST_BE_OFF')
 if (B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():fail('OWNER_GATE_CHANGED')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():fail('DELIVERY_GATE_CLOSED')
 if not LIVE_DB.is_file() or LIVE_DB.is_symlink():fail('LIVE_DB_UNSAFE')
 userupdate=archived_update()
 sys.path.insert(0,str(B))
 import rg_moderation as m
 cfg=m.config()
 private_chat=(userupdate.get('callback_query') or {}).get('message',{}).get('chat',{}).get('id')
 actor=(userupdate.get('callback_query') or {}).get('from',{}).get('id')
 if int(cfg['moderation_chat_id']) not in cfg['moderators'] or private_chat!=actor or private_chat!=cfg['moderation_chat_id']:
  fail('ACTOR_OR_CHAT_NOT_AUTHORIZED')
 old_db_connect=m.db_connect;old_api=m.api
 try:
  res=[scenario('recheck',userupdate,m,cfg,old_db_connect,LIVE_DB),
       scenario('reject',userupdate,m,cfg,old_db_connect,LIVE_DB)]
 finally:
  m.db_connect=old_db_connect;m.api=old_api
 status='NEWS2_P38_SHADOW_MODERATION_PASS' if all(x['result']=='PASS' for x in res) else 'NEWS2_P38_SHADOW_MODERATION_NEEDS_FIX'
 emit(status=status,checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  tests=res,source_message_id=8018,source_update_id=615861392,
  production_db_modified=False,temporary_db_removed=True,
  live_telegram_api_calls=0,live_channel_sends=0,
  publication_gate_opened=False,cron_changed=False,
  note='Tests actual moderation handler on isolated copied DB using previously archived authentic callback.')
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='NEWS2_P38_BLOCKED',
   reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
   live_telegram_api_calls=0,live_channel_sends=0)
  sys.exit(1)
