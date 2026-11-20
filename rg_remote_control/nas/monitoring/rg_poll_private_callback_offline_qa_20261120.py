#!/usr/bin/env python3
"""NEWS2 private callback simulation. No bot import, Telegram calls or state writes."""
import ast,copy,hashlib,json,os,pathlib,re,sys,time
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
P=R/'operator/news_rg_poll_moderation_v1.py'
Q=R/'operator/news_rg_poll_quality_v1.py'
def sha(b):return hashlib.sha256(b).hexdigest()
def run():
 if not P.is_file() or P.is_symlink() or not Q.is_file() or Q.is_symlink():
  raise RuntimeError('UNSAFE_OR_MISSING_SOURCE')
 current=P.read_bytes()
 if len(current)>150000:raise RuntimeError('UNEXPECTED_SOURCE_SIZE')
 source=current.decode('utf8')
 tree=ast.parse(source)
 # No fixed SHA: verify the live protection before executing an isolated callback.
 if source.count('POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL')!=1:
  raise RuntimeError('PUBLICATION_PAUSE_MISSING')
 if source.count('RG_POLL_V6_HUMAN_APPROVAL_GATE_20261120')!=2:
  raise RuntimeError('V6_QUALITY_AND_APPROVAL_GATES_CHANGED')
 callbacks=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='callback']
 if len(callbacks)!=1:raise RuntimeError('CALLBACK_COUNT_CHANGED')
 callback_node=callbacks[0]
 def text(n):return ast.get_source_segment(source,n) or ''
 returns=[n for n in ast.walk(callback_node) if isinstance(n,ast.Return)
  and 'POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL' in text(n)]
 claims=[n for n in ast.walk(callback_node) if isinstance(n,ast.Assign)
  and 'PUBLIC_SEND_UNCERTAIN' in text(n)]
 photos=[n for n in ast.walk(callback_node) if isinstance(n,ast.Call)
  and isinstance(n.func,ast.Name) and n.func.id=='send_photo']
 polls=[n for n in ast.walk(callback_node) if isinstance(n,ast.Call)
  and isinstance(n.func,ast.Name) and n.func.id=='telegram'
  and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='sendPoll']
 if len(returns)!=1 or not claims or len(photos)!=1 or len(polls)!=1:
  raise RuntimeError('PUBLIC_SEND_STRUCTURE_CHANGED')
 if not (returns[0].lineno<min(n.lineno for n in claims)<photos[0].lineno<polls[0].lineno):
  raise RuntimeError('PUBLIC_GATE_ORDER_CHANGED')
 if sha(Q.read_bytes())!='bc585371bc693093a5469ca7abc32a09a35a9ebdec67f919223c52a1c05b4e22':
  raise RuntimeError('QA_CHANGED_SAFE_STOP')
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
