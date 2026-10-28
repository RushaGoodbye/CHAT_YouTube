#!/usr/bin/env python3
"""NEWS RG: protected private delivery worker, reusing existing NAS DSM task.

Never reads Telegram updates, never calls publication endpoints, never
starts a second callback worker. Stops at one outstanding editorial card.
"""
import os,sys,json,pathlib,subprocess,time,fcntl,tempfile
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
B=O.parent
SENDER=O/'news_rg_durable_private_sender_v1.py'
M=O/'news_rg_private_multipart_receipts_v1'
D=O/'news_rg_editorial_decisions_v1'
ST=O/'news_rg_private_review_staging'
ANCHOR_ID='e793f4cd55c5246022bf86e8'
ANCHOR_MSG=8050
LOCK=O/'news_rg_private_dispatch.lock'
LOG=O/'news_rg_private_dispatch_status_v1.json'
def fail(reason):raise RuntimeError(reason)
def read(p,limit=20000):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>limit:fail('UNSAFE_FILE_'+p.name)
 return json.loads(p.read_text(encoding='utf-8'))
def receipt_check(p):
 data=read(p)
 if data.get('status') in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY'):
  fail('UNCERTAIN_DELIVERY_PAUSE')
 if data.get('status')!='PRIVATE_SENT_CONFIRMED':
  fail('NONCONFIRMED_DELIVERY_PAUSE')
 dec=D/p.name
 if not dec.is_file():fail('ONE_OUTSTANDING_EDITORIAL_CARD')
 d=read(dec)
 if d.get('draft_id')!=p.stem or d.get('telegram_message_id')!=data.get('message_id'):
  fail('EDITORIAL_DECISION_MISMATCH')
 if d.get('decision') not in ('editorially_accepted_not_published','editorially_rejected'):
  fail('INVALID_EDITORIAL_DECISION')
 if d.get('public_publication')!='OFF':fail('PUBLICATION_GUARD_CHANGED')
def gate():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 worker=O/'rg_news2_p31_guarded_callback_once.py'
 mod=B/'rg_moderation.py'
 if not worker.is_file() or worker.is_symlink() or '# NEWS_RG_NE1_OWNER_ROUTE_V1' not in worker.read_text():fail('EDITORIAL_ROUTE_NOT_INSTALLED')
 if not mod.is_file() or mod.is_symlink() or '# NEWS_RG_EDITORIAL_HOOK_V1' not in mod.read_text():fail('EDITORIAL_MODULE_NOT_INSTALLED')
 owner=O/'callback_v29.py'
 if not owner.is_file() or owner.is_symlink() or "WORKER=O/'rg_news2_p31_guarded_callback_once.py'" not in owner.read_text():fail('CALLBACK_OWNER_CHANGED')
 anchor=read(M/(ANCHOR_ID+'.json'))
 if anchor.get('status')!='PRIVATE_SENT_CONFIRMED' or anchor.get('message_id')!=ANCHOR_MSG:
  fail('HISTORIC_PRIVATE_DELIVERY_NOT_PROVEN')
 if anchor.get('public_publication')!='OFF':fail('PUBLICATION_GUARD_CHANGED')
 if not D.is_dir():
  fail('WAITING_FOR_REAL_EDITORIAL_CALLBACK')
 anchor_dec=D/(ANCHOR_ID+'.json')
 if not anchor_dec.is_file():fail('WAITING_FOR_REAL_EDITORIAL_CALLBACK')
 for receipt in M.glob('*.json'):
  if receipt.is_symlink():fail('RECEIPT_SYMLINK')
  receipt_check(receipt)
 for directory in (ST,M,D):
  if not directory.is_dir() or directory.is_symlink():fail('UNSAFE_DIRECTORY_'+directory.name)
 if not SENDER.is_file() or SENDER.is_symlink():fail('PERSISTENT_SENDER_MISSING')
 return {'status':'PRIVATE_DISPATCH_ARMED','confirmed_anchor':ANCHOR_MSG,'outstanding':0,
    'second_poller':False,'publications':0}
def state(result):
 LOG.parent.mkdir(exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.news_rg_dispatch_',dir=str(O))
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as h:
   os.chmod(tmp,0o600)
   json.dump(result,h,ensure_ascii=False,sort_keys=True)
   h.flush();os.fsync(h.fileno())
  os.replace(tmp,LOG)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def act():
 gate()
 proc=subprocess.run(['/usr/bin/python3',str(SENDER),'send-one'],
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=80)
 try: result=json.loads(proc.stdout.strip().splitlines()[-1])
 except (ValueError,IndexError):fail('SENDER_OUTPUT_INVALID')
 if proc.returncode and result.get('reason')=='NO_NEW_ELIGIBLE_DRAFT':
  return {'status':'NO_ELIGIBLE_DRAFT','publications':0,'telegram_sends':0}
 if proc.returncode:fail('PRIVATE_SEND_BLOCKED_'+str(result.get('reason','UNKNOWN'))[:70])
 if result.get('status')!='PRIVATE_SENT_CONFIRMED':fail('TELEGRAM_ACK_NOT_CONFIRMED')
 return {'status':'PRIVATE_SENT_CONFIRMED','message_id':result.get('message_id'),
         'draft_id':result.get('draft_id'),'publications':0}
def main():
 if sys.argv[1:]==['selftest']:
  assert ANCHOR_MSG>0 and len(ANCHOR_ID)==24
  print('NEWS_RG_DURABLE_PRIVATE_DISPATCH_SELFTEST_PASS');return
 if sys.argv[1:]==['status']:
  try: result=gate()
  except Exception as ex:result={'status':'PAUSED','reason':str(ex)[:100],'publications':0}
  print(json.dumps(result,ensure_ascii=False,sort_keys=True));return
 if sys.argv[1:]!=['run-once']:fail('BAD_MODE')
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (OSError,BlockingIOError):
   print(json.dumps({'status':'ALREADY_RUNNING','publications':0}));return
  try:result=act()
  except Exception as e:result={'status':'PAUSED','reason':str(e)[:100],'publications':0}
  state(result)
  print(json.dumps(result,ensure_ascii=False,sort_keys=True))
 finally:
  os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:120],'publications':0}))
  sys.exit(2)
