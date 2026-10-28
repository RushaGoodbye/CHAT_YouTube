#!/usr/bin/env python3
"""NEWS RG: verify private callback for card 8052, then safely run ONE AI tick.

Does not poll Telegram, alter callbacks, change publication gate, or bypass
existing private-dispatch locks. Does not publish to the channel. Never attempts
the AI tick unless the existing Telegram callback ledger confirms REJECT for
the exact previously delivered private message.
"""
import os,sys,json,pathlib,subprocess,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
DRAFT_ID='aaf7d9f6968c17f0ff8c4507'
MESSAGE_ID=8052
DEC=O/'news_rg_editorial_decisions_v1'/(DRAFT_ID+'.json')
RECEIPT=O/'news_rg_private_multipart_receipts_v1'/(DRAFT_ID+'.json')
DISPATCH=O/'news_rg_durable_private_dispatch_v1.py'
FINAL_TICK=O/'news_rg_final_tick_v1.py'
STAGING=O/'news_rg_private_review_staging'
PRIVATE=O/'news_rg_private_multipart_receipts_v1'
def report(**kw):print(json.dumps(kw,ensure_ascii=False,sort_keys=True))
def read(p):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>20000:
  raise RuntimeError('MISSING_OR_UNSAFE_'+p.name)
 obj=json.loads(p.read_text(encoding='utf8'))
 if not isinstance(obj,dict):raise RuntimeError('INVALID_JSON_'+p.name)
 return obj
def ledger():
 receipt=read(RECEIPT)
 if receipt.get('status')!='PRIVATE_SENT_CONFIRMED' or receipt.get('message_id')!=MESSAGE_ID or receipt.get('draft_id')!=DRAFT_ID:
  raise RuntimeError('CARD_8052_DELIVERY_RECEIPT_MISMATCH')
 if not DEC.is_file():
  return {'status':'CALLBACK_NOT_YET_SAVED','message_id':MESSAGE_ID,
    'publications':0,'pollers_started':0}
 d=read(DEC)
 if d.get('draft_id')!=DRAFT_ID or d.get('telegram_message_id')!=MESSAGE_ID or d.get('public_publication')!='OFF':
  raise RuntimeError('CARD_8052_DECISION_RECEIPT_MISMATCH')
 return {'status':'CONFIRMED' if d.get('decision')=='editorially_rejected' else 'NOT_REJECTED',
  'decision':d.get('decision'),'message_id':MESSAGE_ID,'publications':0,'pollers_started':0}
def dispatch_status():
 if not DISPATCH.is_file() or DISPATCH.is_symlink():
  raise RuntimeError('PRIVATE_DISPATCH_MISSING')
 proc=subprocess.run([sys.executable,str(DISPATCH),'status'],capture_output=True,text=True,timeout=12)
 try:return json.loads(proc.stdout.strip().splitlines()[-1])
 except (ValueError,IndexError):raise RuntimeError('DISPATCH_STATUS_UNREADABLE')
def receipts():
 if PRIVATE.is_symlink() or not PRIVATE.is_dir():raise RuntimeError('RECEIPTS_DIR_UNSAFE')
 result={}
 for p in PRIVATE.glob('*.json'):
  if p.is_symlink():continue
  try:
   data=read(p)
   if data.get('status')=='PRIVATE_SENT_CONFIRMED' and isinstance(data.get('message_id'),int):
    result[p.stem]=data['message_id']
  except (ValueError,OSError,RuntimeError):continue
 return result
def run():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 state=ledger()
 if state['status']!='CONFIRMED':
  report(**state)
  return
 before_status=dispatch_status()
 if before_status.get('status')!='PRIVATE_DISPATCH_ARMED':
  report(status='CARD_8052_REJECTION_SAVED_BUT_DISPATCH_NOT_READY',
    reason=str(before_status.get('reason',before_status.get('status')))[:100],
    previous_message_id=MESSAGE_ID,publications=0,pollers_started=0)
  return
 tick=FINAL_TICK
 if tick.is_symlink() or not tick.is_file():raise RuntimeError('AI_TICK_MISSING')
 code=tick.read_text(encoding='utf8')
 if 'NEWS_RG_INSTANT_PRIVATE_HANDOFF_V1' not in code or 'news_rg_durable_private_dispatch_v1.py' not in code:
  raise RuntimeError('INSTANT_PRIVATE_HANDOFF_NOT_INSTALLED')
 before=receipts()
 try:
  executed=subprocess.run([sys.executable,str(tick)],
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                          timeout=315)
 except subprocess.TimeoutExpired:
  report(status='AI_TICK_TIMEOUT_CHECK_RECEIPTS_BEFORE_RETRY',
    previous_message_id=MESSAGE_ID,publications=0,pollers_started=0)
  return
 after=receipts()
 new=[{'draft_id':key,'message_id':value} for key,value in after.items()
      if key not in before and value>MESSAGE_ID]
 nextstatus=dispatch_status()
 if new:
  new.sort(key=lambda x:x['message_id'])
  report(status='NEXT_PRIVATE_CARD_CONFIRMED',new_cards=new,
    ai_tick_exit=executed.returncode,
    previous_rejection_confirmed=True,publications=0,pollers_started=0)
 else:
  report(status='NO_NEW_CARD_AFTER_ONE_GUARDED_AI_TICK',
    ai_tick_exit=executed.returncode,
    private_dispatch_status=nextstatus.get('status'),
    private_dispatch_reason=str(nextstatus.get('reason',''))[:100],
    staging_files=len(list(STAGING.glob('*.json'))) if STAGING.is_dir() else None,
    previous_rejection_confirmed=True,publications=0,pollers_started=0)
def selftest():
 assert len(DRAFT_ID)==24 and MESSAGE_ID==8052
 assert (O/'news_rg_editorial_decisions_v1'/(DRAFT_ID+'.json'))==DEC
 print('NEWS_RG_REJECTED_CARD_NEXT_TICK_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['verify-and-run-once']:run()
  elif sys.argv[1:]==['verify-only']:
   if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
   report(**ledger(),dispatch_status=dispatch_status().get('status'))
  else:raise RuntimeError('BAD_MODE')
 except Exception as e:
  report(status='SAFE_STOP',reason=str(e)[:120],publications=0,pollers_started=0)
  sys.exit(2)
