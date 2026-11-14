#!/usr/bin/env python3
"""NEWS2 RG3 legacy moderation action integration. Local SQLite only.
No real Telegram API, NAS writes, channel sends, or bot polling.
"""
import sys,types,sqlite3,tempfile,datetime,json,importlib.util
from pathlib import Path
ROOT=Path(r'\\192.168.50.32\docker\RG_TELEGRAM_NEWS_2')
with tempfile.TemporaryDirectory(prefix='news2_rg3_actions_') as tmp:
 dbpath=Path(tmp)/'callbacks.sqlite3'
 fake=types.ModuleType('rg_news')
 fake.BASE=Path(tmp)
 fake.now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
 fake.audit=lambda *args,**kw:None
 connections=[]
 def connect():
  db=sqlite3.connect(dbpath)
  db.row_factory=sqlite3.Row
  connections.append(db)
  db.execute('CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY,status TEXT NOT NULL,photo_reviewed INTEGER,updated_at TEXT,created_at TEXT)')
  return db
 fake.connect=connect
 sys.modules['rg_news']=fake
 spec=importlib.util.spec_from_file_location('rg_moderation_offline',str(ROOT/'rg_moderation.py'))
 m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
 actions=[]
 m.api=lambda method,payload:actions.append((method,payload)) or {'ok':True}
 cfg={'moderators':[12345],'moderation_chat_id':12345}
 def plant(key):
  with m.db_connect() as db:
   db.execute('INSERT INTO candidates (id,status,photo_reviewed,updated_at,created_at) VALUES (?,?,?,?,?)',
       (key,'awaiting_moderation',1,'now','now'))
   db.execute('INSERT INTO moderation_dispatch(candidate_id,state,message_id,updated_at) VALUES (?,?,?,?)',
       (key,'sent',471,'now'))
 def run(action,key,user=12345,msg=471):
  return m.process_callback({'callback_query':{'data':f'rg3:{action}:{key}',
      'from':{'id':user},'message':{'message_id':msg,'chat':{'id':12345,'type':'private'}}}},cfg)
 statuses={}
 for i,(action,expected) in enumerate([('recheck','needs_recheck'),
                                      ('similar','needs_duplicate_review'),
                                      ('reject','rejected')]):
  key=f'{i+1:024x}'
  plant(key)
  forged=run(action,key,user=9999)
  assert forged['status']=='UNAUTHORIZED',forged
  wrongmsg=run(action,key,msg=999)
  assert wrongmsg['status']=='UNMATCHED_CARD',wrongmsg
  result=run(action,key)
  assert result['status']==expected,result
  with m.db_connect() as db:
   state=db.execute('SELECT status FROM candidates WHERE id=?',(key,)).fetchone()['status']
  assert state==expected
  repeat=run(action,key)
  assert repeat['status']=='ALREADY_HANDLED',repeat
  statuses[action]={'changed_once':True,'repeated_blocked':True}
 key='f'*24;plant(key)
 assert run('approve',key)['status']=='APPROVAL_DISABLED_UNTIL_CUTOVER'
 with m.db_connect() as db:
  assert db.execute('SELECT status FROM candidates WHERE id=?',(key,)).fetchone()['status']=='awaiting_moderation'
 assert actions and all(method=='deleteMessage' and x.get('chat_id')==12345 for method,x in actions)
 for db in connections:db.close()
 print(json.dumps({'status':'NEWS2_RG3_BUTTONS_REAL_CODE_SQLITE_ISOLATED_PASS',
   'actions':statuses,'legacy_approve_paused':True,
   'network_calls':0,'nas_writes':0,'publications':0},ensure_ascii=False))
