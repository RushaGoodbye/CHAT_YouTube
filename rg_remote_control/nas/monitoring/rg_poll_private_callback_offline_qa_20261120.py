#!/usr/bin/env python3
"""NEWS2 private callback simulation. No bot import, Telegram calls or state writes."""
import ast,copy,hashlib,json,os,pathlib,re,sys,time
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
P=R/'operator/news_rg_poll_moderation_v1.py'
Q=R/'operator/news_rg_poll_quality_v1.py'
def sha(b):return hashlib.sha256(b).hexdigest()
def run():
 if sha(P.read_bytes())!='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb':
  raise RuntimeError('SOURCE_CHANGED_SAFE_STOP')
 if sha(Q.read_bytes())!='bc585371bc693093a5469ca7abc32a09a35a9ebdec67f919223c52a1c05b4e22':
  raise RuntimeError('QA_CHANGED_SAFE_STOP')
 tree=ast.parse(P.read_text('utf8'))
 hits=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='callback']
 if len(hits)!=1:raise RuntimeError('CALLBACK_CHANGED')
 sys.path.insert(0,str(P.parent))
 callback_only=ast.fix_missing_locations(ast.Module(body=hits,type_ignores=[]))
 sample={'id':'a'*20,'status':'PENDING','private_message_id':123,
  'question':'Який формат новин для вас найзручніший?',
  'options':['Короткі повідомлення','Відео з поясненнями','Підсумок дня','Розбір ключових подій'],
  'media_qa':'PASS','topic':{'independent_sources':2,'title':'Тест'},'created_at':int(time.time())}
 baseline={'current':'a'*20,'publications':0,'variants':[sample]}
 writes=[];network=[]
 sandbox={'re':re,'os':os,'time':time,'datekey':lambda:'2026-11-20',
  'lock':lambda:os.open('/dev/null',os.O_RDONLY),
  'load':lambda _:copy.deepcopy(baseline),
  'store':lambda x:writes.append(copy.deepcopy(x)),
  'telegram':lambda *a,**kw:network.append((a,kw)),
  'CHANNEL':'@NEVER_SEND','LINKS':'https://example.org'}
 exec(compile(callback_only,'<news2-callback-sandbox>','exec'),sandbox)
 def call(action,who=12345,message_id=123):
  return sandbox['callback']({'callback_query':{'data':'rp1:'+action+':'+sample['id'],
   'from':{'id':who},'message':{'message_id':message_id,
   'chat':{'type':'private','id':12345}}}},
   {'moderation_chat_id':12345,'moderators':[12345]})
 outcomes={'unauthorized':call('pub',who=99999).get('status'),
  'old_button':call('pub',message_id=124).get('status'),
  'publication':call('pub').get('status'),
  'redo':call('redo').get('status'),
  'reject':call('reject').get('status')}
 expected={'unauthorized':'POLL_MODERATOR_UNAUTHORIZED',
  'old_button':'POLL_OLD_OR_ALREADY_DECIDED',
  'publication':'POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL',
  'redo':'POLL_REDO_QUEUED','reject':'POLL_REJECTED'}
 if outcomes!=expected:raise RuntimeError('CALLBACK_OUTCOME_MISMATCH:'+json.dumps(outcomes))
 if len(writes)!=2 or network:raise RuntimeError('SIDE_EFFECT_CONTRACT_FAILED')
 return {'status':'RG_POLL_PRIVATE_CALLBACK_OFFLINE_PASS','checks':outcomes,
  'simulated_state_writes':len(writes),'real_state_writes':0,
  'telegram_calls':0,'publications':0,'new_pollers':0}
if __name__=='__main__':
 try:print(json.dumps(run(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_PRIVATE_CALLBACK_SAFE_STOP','reason':str(e)[:170],
   'telegram_calls':0,'publications':0},ensure_ascii=False));sys.exit(2)
