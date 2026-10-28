#!/usr/bin/env python3
"""NEWS RG offline callback integration tests. Temporary files only; NO Telegram calls."""
import os,sys,json,pathlib,tempfile,importlib.util
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path)
 module=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(module)
 return module
def main():
 callback=load('/tmp/news_rg_editorial_callbacks_v1.py','newsrg_callback_test')
 key='a'*24
 key2='b'*24
 with tempfile.TemporaryDirectory(prefix='newsrg_cb_test_') as work:
  root=pathlib.Path(work)
  callback.ST=root/'staging';callback.RECEIPTS=root/'receipts';callback.DECISIONS=root/'decisions'
  callback.ST.mkdir();callback.RECEIPTS.mkdir()
  for draft in (key,key2):
   (callback.ST/(draft+'.json')).write_text(json.dumps({'draft_id':draft,
     'editorial_status':'HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED','public_publication':'OFF'}))
   (callback.RECEIPTS/(draft+'.json')).write_text(json.dumps({'draft_id':draft,
     'status':'PRIVATE_SENT_CONFIRMED','message_id':123}))
  cfg={'moderation_chat_id':456,'moderators':[456]}
  def event(action,draft,who=456,chat=456,msg=123):
   return {'callback_query':{'data':'ne1:'+action+':'+draft,'from':{'id':who},
      'message':{'message_id':msg,'chat':{'id':chat,'type':'private'}}}}
  assert callback.process_callback({'callback_query':{'data':'rg3:approve:'+key}},cfg) is None
  assert callback.process_callback(event('accept',key,who=777),cfg)['status']=='EDITORIAL_USER_NOT_ALLOWED'
  assert callback.process_callback(event('accept',key,chat=777),cfg)['status']=='EDITORIAL_PRIVATE_CHAT_REQUIRED'
  assert callback.process_callback(event('accept',key,msg=124),cfg)['status']=='EDITORIAL_MESSAGE_MISMATCH'
  assert not list((root/'decisions').glob('*.json')) if (root/'decisions').exists() else True
  accepted=callback.process_callback(event('accept',key),cfg)
  assert accepted['status']=='EDITORIAL_ACCEPTED_NO_PUBLICATION',accepted
  saved=json.loads((root/'decisions'/(key+'.json')).read_text())
  assert saved['decision']=='editorially_accepted_not_published'
  assert saved['public_publication']=='OFF'
  assert callback.process_callback(event('reject',key),cfg)['status']=='EDITORIAL_ALREADY_DECIDED'
  rejected=callback.process_callback(event('reject',key2),cfg)
  assert rejected['status']=='EDITORIAL_REJECTED',rejected
  assert json.loads((root/'decisions'/(key2+'.json')).read_text())['decision']=='editorially_rejected'
 print(json.dumps({'status':'NEWS_RG_EDITORIAL_OFFLINE_ACCEPTANCE_PASS',
   'tests':['legacy_isolation','moderator_allowlist','private_chat','message_binding',
            'idempotent_accept','separate_reject','publication_off'],
   'telegram_calls':0,'production_db_writes':0,'publications':0}))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'SELFTEST_FAILED','error_type':type(e).__name__,'publications':0}))
  raise SystemExit(2)
