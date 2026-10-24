#!/usr/bin/env python3
"""RG NEWS2 P42 RELEASE GATE
Replay the INSTALLED moderation worker and the real moderation handler in
an isolated SQLite copy using simulated Telegram replies. No network or live
API, no live cron/DB writes, and no news-channel publication.
"""
import ast,copy,datetime,hashlib,importlib.util,json,os,pathlib,re,sqlite3,sys,tempfile

BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
LIVE=BASE/'news.sqlite3'
HANDLER=BASE/'rg_moderation.py'
WORKER=OP/'rg_news2_p31_guarded_callback_once.py'
STATE=OP/'callback_v29_state.json'
EXPECTED_HANDLER='2090ca71215f71cef7f72743e8efc9b69ed0fd6d665ff91f98e555eb2f4be0ff'
EXPECTED_WORKER='eceba0756c1de522a24122075c236f4eac5f185e'
EXPECTED_POLL='8c2fef89eb62af682afe86f1d7034c87248bc61e'
BOT_ID=7492268627

def emit(**v):print(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True),flush=True)
def stop(reason):raise RuntimeError(reason)
def git_blob(raw):
 return hashlib.sha1(('blob %d\0'%len(raw)).encode('ascii')+raw).hexdigest()

def source_guards():
 if os.geteuid()!=0:stop('SUDO_REQUIRED')
 if not LIVE.is_file() or LIVE.is_symlink():stop('NEWS_DB_UNSAFE')
 if not HANDLER.is_file() or HANDLER.is_symlink():stop('HANDLER_UNSAFE')
 if not WORKER.is_file() or WORKER.is_symlink():stop('WORKER_UNSAFE')
 if (BASE/'PUBLISH_ENABLED').exists():stop('PUBLICATION_GATE_OPEN')
 if (BASE/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():stop('OWNERSHIP_GATE_CHANGED')
 if (pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')).exists():stop('LEGACY_GATE_OPEN')
 if not (BASE/'MODERATION_DELIVERY_ENABLED').is_file():stop('MODERATION_GATE_CLOSED')
 if hashlib.sha256(HANDLER.read_bytes()).hexdigest()!=EXPECTED_HANDLER:stop('HANDLER_SOURCE_SHA_CHANGED')
 if git_blob(WORKER.read_bytes())!=EXPECTED_WORKER:stop('INSTALLED_WORKER_SOURCE_CHANGED')
 poll=OP/'callback_v29.py'
 if not poll.is_file() or git_blob(poll.read_bytes())!=EXPECTED_POLL:stop('INSTALLED_PROBATION_SOURCE_CHANGED')
 n=ast.parse(HANDLER.read_text('utf8'))
 fn=[x for x in n.body if isinstance(x,ast.FunctionDef) and x.name=='process_callback']
 if len(fn)!=1:stop('HANDLER_MISSING')
 names=[]
 for call in ast.walk(fn[0]):
  if not isinstance(call,ast.Call):continue
  if isinstance(call.func,ast.Attribute):names.append(call.func.attr)
  elif isinstance(call.func,ast.Name):names.append(call.func.id)
  else:stop('DYNAMIC_HANDLER_CALL')
 if not set(names)<=set(('get','isinstance','fullmatch','groups','db_connect','execute','fetchone','now','audit','str')):
  stop('HANDLER_CALLS_CHANGED')

def live_health():
 out={}
 if STATE.is_file() and not STATE.is_symlink():
  s=json.loads(STATE.read_text('utf8'))
  out['attempts']=s.get('attempts')
  out['successes']=s.get('successes')
  out['halt']=s.get('halt')
  out['last']=s.get('last')
  out['last_offset']=s.get('last_offset')
  out['last_error_class']=s.get('last_error_class')
  out['last_poll_utc']=s.get('last_poll_utc')
  if s.get('last_poll_utc'):
   dt=datetime.datetime.fromisoformat(s['last_poll_utc'].replace('Z','+00:00'))
   age=(datetime.datetime.now(datetime.timezone.utc)-dt).total_seconds()
   out['last_poll_age_seconds']=int(age)
   out['heartbeat_fresh']=0<=age<180
 else:out['state_missing']=True
 cr=pathlib.Path('/etc/crontab').read_text('utf8')
 out['cron_count']=sum('RG_NEWS2_CALLBACK_PROBATION_V29' in s and not s.lstrip().startswith('#') for s in cr.splitlines())
 with sqlite3.connect('file:'+str(LIVE)+'?mode=ro',uri=True,timeout=8) as c:
  out['pending_private_cards']=c.execute("""SELECT COUNT(*) FROM candidates c
   JOIN moderation_dispatch d ON d.candidate_id=c.id
   WHERE d.state='sent' AND c.status IN ('awaiting_photo_review','awaiting_moderation')""").fetchone()[0]
  r=c.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  out['live_offset']=int(r[0]) if r else None
 return out

def offline_integrate():
 sys.path.insert(0,str(BASE))
 import rg_moderation as m
 import rg_news
 cfg=m.config()
 chat=int(cfg['moderation_chat_id'])
 if chat<=0 or chat not in cfg['moderators']:stop('MODERATOR_CONFIG_INVALID')
 with sqlite3.connect('file:'+str(LIVE)+'?mode=ro',uri=True,timeout=8) as c:
  c.row_factory=sqlite3.Row
  row=c.execute("""SELECT c.id,d.message_id FROM candidates c
   JOIN moderation_dispatch d ON d.candidate_id=c.id
   WHERE d.state='sent' AND c.status IN ('awaiting_photo_review','awaiting_moderation')
   ORDER BY d.message_id DESC LIMIT 1""").fetchone()
  if not row:stop('NO_PENDING_AUTHENTIC_MODERATION_CARD')
  cid=str(row['id']);mid=int(row['message_id'])
  if not re.fullmatch('[a-f0-9]{24}',cid):stop('CANDIDATE_ID_FORMAT_CHANGED')
 out=[]
 spec=importlib.util.spec_from_file_location('rg_news2_p42_worker',str(WORKER))
 worker=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(worker)
 orig_m_db=m.db_connect;orig_m_api=m.api;orig_m_cfg=m.config
 orig_news_api=getattr(rg_news,'api',None)
 orig_sqlite=sqlite3.connect
 orig_args=sys.argv
 for kind,want in (
   ('reject','rejected'),
   ('recheck','needs_recheck'),
   ('similar','needs_duplicate_review'),
   ('approve','awaiting_photo_review'),
   ('unauthorized','awaiting_photo_review'),
   ('test','awaiting_photo_review')):
  with tempfile.TemporaryDirectory(prefix='rg_news2_p42_') as folder:
   sandbox=pathlib.Path(folder)
   copyfile=sandbox/'news.sqlite3'
   fakebase=sandbox/'nas_fake'
   fakeop=fakebase/'operator';fakeop.mkdir(parents=True)
   (fakebase/'MODERATION_DELIVERY_ENABLED').touch()
   with orig_sqlite('file:'+str(LIVE)+'?mode=ro',uri=True,timeout=8) as prod:
    with orig_sqlite(str(copyfile)) as dest:prod.backup(dest)
   with orig_sqlite(str(copyfile)) as db:
    db.execute("UPDATE candidates SET status='awaiting_photo_review',photo_reviewed=0 WHERE id=?",(cid,))
    q=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
    offset=int(q[0]) if q else 615861400
   calls=[]
   def shadow_connect(*args,**kwargs):
    path=str(args[0] if args else kwargs.get('database',''))
    if path!=str(copyfile):stop('ISOLATED_DB_ESCAPE_BLOCKED')
    db=orig_sqlite(str(copyfile),timeout=10)
    db.row_factory=sqlite3.Row
    return db
   def fake_api(method,payload):
    calls.append({'method':method,'chat_id':payload.get('chat_id') if isinstance(payload,dict) else None})
    if method=='getMe':return {'id':BOT_ID}
    if method=='getWebhookInfo':return {'url':''}
    if method=='getUpdates':return [update]
    if method=='answerCallbackQuery':return True
    if method in ('sendMessage','editMessageReplyMarkup'):
     if payload.get('chat_id')!=chat:stop('OUTBOUND_TO_UNKNOWN_RECIPIENT')
     return {'message_id':999999} if method=='sendMessage' else True
    stop('UNEXPECTED_TELEGRAM_METHOD_'+str(method))
   actor=chat+1 if kind=='unauthorized' else chat
   action='reject' if kind=='unauthorized' else kind
   data=('rgprobe25:'+'a'*18) if kind=='test' else ('rg3:'+action+':'+cid)
   messageid=8032 if kind=='test' else mid
   update={'update_id':offset+1,'callback_query':{
    'id':'offline_p42_'+kind,'from':{'id':actor,'is_bot':False},
    'message':{'message_id':messageid,
     'from':{'id':BOT_ID,'username':'RushaGoodbyeNews_bot','is_bot':True},
     'chat':{'id':chat,'type':'private'}},'data':data}}
   captured=[]
   worker.B=fakebase;worker.O=fakeop;worker.LEG=fakebase/'legacy'
   worker.emit=lambda **kv:captured.append(kv)
   m.db_connect=lambda:shadow_connect(str(copyfile))
   m.api=fake_api;m.config=lambda:cfg
   rg_news.api=lambda *args,**kwargs:stop('RG_NEWS_DIRECT_API_FORBIDDEN')
   sqlite3.connect=shadow_connect
   sys.argv=[str(WORKER),'once']
   try:
    worker.main()
    if len(captured)!=1 or captured[0].get('status')!='ONE_SHOT_CALLBACK_HANDOFF_COMPLETE':
     stop('WORKER_REPLAY_NO_SUCCESS_'+kind)
    with shadow_connect(str(copyfile)) as db:
     after=db.execute("SELECT status FROM candidates WHERE id=?",(cid,)).fetchone()[0]
     newoffset=int(db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()[0])
    if after!=want:stop('UNEXPECTED_CANDIDATE_TRANSITION_'+kind)
    if newoffset!=offset+2:stop('UPDATE_OFFSET_MISMATCH_'+kind)
    log=captured[0]
    if log.get('update_count')!=1 or len(log.get('outcomes') or [])!=1:
     stop('UPDATE_COUNT_MISMATCH_'+kind)
    statuses=[c['method'] for c in calls]
    should_confirm=kind in ('reject','recheck','similar','test')
    if ('sendMessage' in statuses)!=should_confirm:stop('VISIBLE_REPLY_MISMATCH_'+kind)
    if ('editMessageReplyMarkup' in statuses)!=(kind in ('reject','recheck','similar')):
     stop('BUTTON_EDIT_MISMATCH_'+kind)
    if 'answerCallbackQuery' not in statuses:stop('NO_CALLBACK_ACK_'+kind)
    if kind=='approve' and log['outcomes']!=['APPROVAL_PAUSED_PUBLISH_DISABLED']:
     stop('APPROVAL_NOT_PAUSED')
    if kind=='unauthorized' and log['outcomes']!=['UNRECOGNIZED_OR_TEST_CALLBACK_ARCHIVED']:
     stop('UNAUTHORIZED_ACTION_NOT_BLOCKED')
    if kind=='test' and log['outcomes']!=['TEST_BUTTON_VISIBLE_CONFIRMATION_SENT']:
     stop('TEST_CONFIRMATION_NOT_SENT')
    if any(c.get('chat_id') not in (None,chat) for c in calls):
     stop('FOREIGN_CHANNEL_SEND_DETECTED')
    out.append({'action':kind,'result':'PASS',
      'state':after,'private_reply_sent':'sendMessage' in statuses,
      'buttons_cleared':'editMessageReplyMarkup' in statuses,
      'telegram_network_calls':0})
   finally:
    m.db_connect=orig_m_db;m.api=orig_m_api;m.config=orig_m_cfg
    sqlite3.connect=orig_sqlite
    if orig_news_api is None:
     if hasattr(rg_news,'api'):delattr(rg_news,'api')
    else:rg_news.api=orig_news_api
    sys.argv=orig_args
 return {'source_card_message_id':mid,'cases':out}

def main():
 source_guards()
 health=live_health()
 checks=offline_integrate()
 status='NEWS2_P42_OFFLINE_INTEGRATION_PASS'
 if (health.get('cron_count')!=1 or health.get('halt') is not None or
       not health.get('heartbeat_fresh',False)):
  status='NEWS2_P42_OFFLINE_INTEGRATION_PASS_LIVE_POLL_UNVERIFIED'
 emit(status=status,shadow=checks,probation=health,
   no_live_telegram_calls=True,publication_off=True,
   no_production_db_changes=True,no_cron_changes=True,
   still_needs_real_moderation_button_e2e=True)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='NEWS2_P42_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
   publication_off=True,no_live_telegram_calls=True)
  sys.exit(1)
