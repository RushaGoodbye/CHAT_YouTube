#!/usr/bin/env python3
"""RG Telegram News 2.0 P41 — real handler on isolated DB, read-only live audit.
Requires matching confirmed NAS handler SHA-256. Zero Telegram API operations.
"""
import ast,copy,datetime,hashlib,json,os,pathlib,sqlite3,sys,tempfile
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
S=B/'rg_moderation.py'
D=B/'news.sqlite3'
EXPECTED='2090ca71215f71cef7f72743e8efc9b69ed0fd6d665ff91f98e555eb2f4be0ff'
VALID_ACTIONS={'recheck':'needs_recheck','reject':'rejected','similar':'needs_duplicate_review','approve':'approved_for_publication'}
def emit(**k): print(json.dumps(k,ensure_ascii=False,sort_keys=True,indent=2),flush=True)
def abort(x):raise RuntimeError(x)
def read_only_health():
 report={}
 p=O/'callback_v29_state.json'
 if p.exists():
  state=json.loads(p.read_text('utf-8'))
  report['probation']={k:state.get(k) for k in ('attempts','successes','failures','halt','last','last_offset','last_poll_utc','last_update_count','last_error_class','expires_at')}
 else: report['probation']={'missing':True}
 f=O/'callback_v29.log'
 if f.exists():
  with f.open('rb') as fp:
   if f.stat().st_size>200000:fp.seek(-200000,2)
   rows=fp.read().decode('utf-8',errors='replace').splitlines()
  last=[]
  for line in rows:
   try: d=json.loads(line)
   except Exception:continue
   if not isinstance(d,dict) or not str(d.get('status','')).startswith('V29_'):continue
   if d.get('updates') or d.get('status')!='V29_POLL_PASS':last.append({key:d.get(key) for key in ('status','updates','outcomes','error_class','halted')})
  report['interesting_ticks']=last[-8:]
  report['log_age_seconds']=int(datetime.datetime.now().timestamp()-f.stat().st_mtime)
 with sqlite3.connect('file:'+str(D)+'?mode=ro',uri=True,timeout=8) as db:
  db.row_factory=sqlite3.Row
  report['active_cards']=[dict(row) for row in db.execute(
   """SELECT d.message_id,d.state AS dispatch_state,c.status AS candidate_status
   FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id
   WHERE d.state IN ('sent','send_uncertain') AND c.status IN ('awaiting_photo_review','awaiting_moderation')
   ORDER BY d.message_id DESC LIMIT 10""")]
  row=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  report['stored_offset']=int(row[0]) if row else None
 report['publishing_disabled']=(not (B/'PUBLISH_ENABLED').exists())
 return report
def handler_preflight():
 if not S.is_file() or S.is_symlink():abort('SOURCE_MISSING_OR_LINK')
 raw=S.read_bytes()
 actual=hashlib.sha256(raw).hexdigest()
 if actual!=EXPECTED:abort('HANDLER_SHA_CHANGED_NEEDS_REVIEW')
 n=ast.parse(raw.decode('utf-8'))
 defs=[v for v in n.body if isinstance(v,ast.FunctionDef) and v.name=='process_callback']
 if len(defs)!=1:abort('CALLBACK_HANDLER_COUNT_NOT_ONE')
 fn=defs[0]
 # Verify the actual confirmed source only updates the database; safe to invoke on clone.
 names=[]
 for el in ast.walk(fn):
  if not isinstance(el,ast.Call):continue
  if isinstance(el.func,ast.Name):names.append(el.func.id)
  elif isinstance(el.func,ast.Attribute):names.append(el.func.attr)
  else:abort('UNKNOWN_DYNAMIC_CALL_IN_HANDLER')
 if not set(names)<=set(('get','isinstance','fullmatch','groups','db_connect','execute','fetchone','now','audit','str')):
  abort('HANDLER_HAS_UNREVIEWED_CALL')
 return sorted(set(names))
def run_shadow():
 sys.path.insert(0,str(B))
 import rg_moderation as m
 import rg_news
 cfg=m.config()
 chat=int(cfg['moderation_chat_id'])
 if chat<=0 or chat not in cfg['moderators']:abort('MODERATOR_CONFIG_INVALID')
 original_connect=m.db_connect;original_api=m.api
 original_sqlite=sqlite3.connect
 original_news_api=getattr(rg_news,'api',None)
 result=[]
 with tempfile.TemporaryDirectory(prefix='rgnews_p41_shadow_') as tmp:
  shadow=pathlib.Path(tmp)/'news.sqlite3'
  with original_sqlite('file:'+str(D)+'?mode=ro',uri=True,timeout=10) as production:
   with original_sqlite(str(shadow)) as db:production.backup(db)
  with original_sqlite(str(shadow)) as db:
   db.row_factory=sqlite3.Row
   card=db.execute("""SELECT c.id,d.message_id FROM moderation_dispatch d
     JOIN candidates c ON d.candidate_id=c.id
     WHERE d.state='sent' AND c.status IN ('awaiting_photo_review','awaiting_moderation')
     ORDER BY d.message_id DESC LIMIT 1""").fetchone()
   if card is None:abort('NO_ACTIVE_SENT_CARD_TO_EXERCISE')
   cid=str(card['id']);mid=int(card['message_id'])
  def safe_connect(*args,**kwargs):
   target=str(args[0] if args else kwargs.get('database',''))
   if target!=str(shadow):abort('SHADOW_CONNECTION_ESCAPED')
   c=original_sqlite(target,timeout=10)
   c.row_factory=sqlite3.Row
   return c
  def forbidden_api(*args,**kwargs):abort('TELEGRAM_CALL_IN_ISOLATED_QA')
  m.db_connect=lambda:safe_connect(str(shadow))
  m.api=forbidden_api
  rg_news.api=forbidden_api
  sqlite3.connect=safe_connect
  try:
   for action,target in VALID_ACTIONS.items():
    # This is deliberately a copied DB. "approve" never touches production.
    with safe_connect(str(shadow)) as db:
     db.execute("UPDATE candidates SET status='awaiting_photo_review',photo_reviewed=0 WHERE id=?",(cid,))
    u={'callback_query':{'from':{'id':chat},'message':{
       'message_id':mid,'chat':{'id':chat,'type':'private'}},
       'data':'rg3:'+action+':'+cid}}
    ret=m.process_callback(copy.deepcopy(u),cfg)
    with safe_connect(str(shadow)) as db:
     after=db.execute('SELECT status FROM candidates WHERE id=?',(cid,)).fetchone()[0]
    if after!=target or ret.get('status')!=target:abort('ACTION_'+action.upper()+'_FAILED')
    result.append({'case':action,'status':'PASS','result':after})
   cases=[
     ('unauthorized',chat+1,mid,'rg3:reject:'+cid,'awaiting_photo_review','UNAUTHORIZED'),
     ('card_mismatch',chat,mid+1,'rg3:reject:'+cid,'awaiting_photo_review','UNMATCHED_CARD'),
     ('bad_action',chat,mid,'rg3:bogus:'+cid,'awaiting_photo_review','INVALID_CALLBACK'),
     ('already_handled',chat,mid,'rg3:reject:'+cid,'rejected','ALREADY_HANDLED')]
   for label,actor,message_id,data,start,expected in cases:
    with safe_connect(str(shadow)) as db:
     db.execute('UPDATE candidates SET status=? WHERE id=?',(start,cid))
    ret=m.process_callback({'callback_query':{'from':{'id':actor},'message':{
        'message_id':message_id,'chat':{'id':chat,'type':'private'}},'data':data}},cfg)
    with safe_connect(str(shadow)) as db:
     after=db.execute('SELECT status FROM candidates WHERE id=?',(cid,)).fetchone()[0]
    if ret.get('status')!=expected or after!=start:abort('NEGATIVE_'+label.upper()+'_FAILED')
    result.append({'case':label,'status':'PASS'})
  finally:
   sqlite3.connect=original_sqlite;m.db_connect=original_connect;m.api=original_api
   if original_news_api is None:delattr(rg_news,'api')
   else:rg_news.api=original_news_api
 return {'source_card_message_id':mid,'cases':result}
def main():
 if os.geteuid()!=0:abort('SUDO_REQUIRED')
 if (B/'PUBLISH_ENABLED').exists():abort('LIVE_PUBLICATION_GATE_ACTIVE')
 if (B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():abort('OWNER_MODE_UNEXPECTED')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():abort('DELIVERY_GATE_CLOSED')
 if not D.is_file() or D.is_symlink():abort('DATABASE_MISSING_OR_LINK')
 reviewed=handler_preflight()
 health=read_only_health()
 qa=run_shadow()
 emit(status='NEWS2_P41_MODERATION_SHADOW_PASS',handler_methods=reviewed,
   shadow=qa,system=health,
   live_database_mutations=0,telegram_api_calls=0,channel_sends=0,
   publishing_changed=False,cron_changed=False,
   note='Checks callback handler offline, not real-time Telegram button delivery.')
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='NEWS2_P41_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
   live_database_mutations=0,telegram_api_calls=0,channel_sends=0)
  sys.exit(1)
