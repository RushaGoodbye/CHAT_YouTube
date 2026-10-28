#!/usr/bin/env python3
"""NEWS RG: current private moderation -> public delivery proof (read-only).

No Bot API, no network, no model, no writes and no scheduler execution.
Inspects the latest private Telegram card after message #8054 and its exact
editorial and publication receipts. Never infers a SEND from mere approval.
"""
import sys,os,time,json,pathlib,datetime,re

BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
AFTER=8054
CHANNEL=-1001755891079
PUB=OP/'news_rg_publication_receipts_v1'
PRIV=OP/'news_rg_private_multipart_receipts_v1'
DEC=OP/'news_rg_editorial_decisions_v1'
ACT=OP/'news_rg_publication_activation_v1.json'
ID_RE=re.compile(r'^[a-f0-9]{24}\.json$')

def load(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>30000:return None
  obj=json.loads(p.read_text(encoding='utf-8'))
  return obj if isinstance(obj,dict) else None
 except (OSError,ValueError,UnicodeError):
  return None

def age(stamp):
 try:
  n=float(stamp)
  if not 1700000000<n<time.time()+3600:return None
  return round(max(0,time.time()-n)/60,2)
 except (ValueError,TypeError,OverflowError):
  return None

def mark(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>100:return None
  return float(p.read_text(encoding='utf-8').strip())
 except (OSError,ValueError,UnicodeError):
  return None

def newest_card():
 if not PRIV.is_dir() or PRIV.is_symlink():raise RuntimeError('PRIVATE_RECEIPTS_DIR_UNSAFE')
 card=None
 for file in PRIV.glob('*.json'):
  if not ID_RE.fullmatch(file.name):continue
  receipt=load(file)
  if not receipt or receipt.get('status')!='PRIVATE_SENT_CONFIRMED':continue
  mid=receipt.get('message_id')
  if not isinstance(mid,int) or isinstance(mid,bool) or mid<=AFTER:continue
  if receipt.get('draft_id')!=file.stem:continue
  if card is None or mid>card[0]:
   card=(mid,file.stem,receipt)
 return card

def recent_log(p):
 try:
  if p.is_symlink() or not p.is_file():return {'present':False}
  with p.open('rb') as f:
   f.seek(max(0,p.stat().st_size-20000))
   lines=f.read().decode('utf-8','replace').splitlines()[-12:]
  out={'present':True,'age_min':age(p.stat().st_mtime)}
  for line in reversed(lines):
   try:
    result=json.loads(line)
    if isinstance(result,dict):
     out['last_status']=str(result.get('status',''))[:80]
     if isinstance(result.get('message_id'),int):
      out['last_message_id']=result['message_id']
     break
   except ValueError:pass
  return out
 except OSError:return {'present':True,'read_error':True}

def classify(d,p,act,receipt,mid):
 if d is None:return 'WAITING_FOR_CALLBACK_DECISION'
 if d.get('telegram_message_id')!=mid or d.get('draft_id')!=receipt.get('draft_id'):
  return 'DECISION_IDENTITY_MISMATCH'
 if d.get('public_publication')!='OFF':return 'EDITORIAL_DECISION_CONTRACT_MISMATCH'
 decision=d.get('decision')
 if decision=='editorially_rejected':
  return 'HUMAN_REJECTED_NO_PUBLICATION_EXPECTED' if p is None else 'REJECTED_WITH_UNEXPECTED_PUBLIC_RECEIPT'
 if decision!='editorially_accepted_not_published':return 'UNEXPECTED_EDITORIAL_DECISION'
 if p:
  if p.get('status')=='PUBLIC_SEND_UNCERTAIN_NO_RETRY':
   return 'PUBLIC_SEND_UNCERTAIN_STOP_NO_RETRY'
  if p.get('status')=='PUBLIC_PUBLISHED_CONFIRMED' and p.get('channel_id')==CHANNEL and isinstance(p.get('message_id'),int):
   return 'PUBLIC_PUBLISHED_CONFIRMED'
  return 'UNEXPECTED_PUBLIC_RECEIPT'
 if not act or act.get('status')!='ACTIVE' or act.get('chat_id')!=CHANNEL:
  return 'PUBLICATION_GATE_NOT_ACTIVE'
 if not isinstance(receipt.get('telegram_photo_file_id'),str):
  return 'PHOTO_FILE_ID_MISSING'
 return 'APPROVED_AWAITING_SCHEDULED_PUBLICATION'

def report():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 latest=newest_card()
 result={
  'schema':'NEWS_RG_LATEST_CARD_AUTONOMY_AUDIT_V1',
  'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'read_only':True,'telegram_calls':0,'ai_calls':0,'publications_triggered':0,
  'new_pollers':0,
  'publication_schedule_last_launch_age_min':age(mark(OP/'news_rg_publication_last_launch')),
  'ai_stage_last_launch_age_min':age(mark(OP/'news_rg_last_launch_utc')),
  'publication_autorun':recent_log(OP/'news_rg_publication_autorun.log'),
  'private_autorun':recent_log(OP/'news_rg_private_dispatch_autorun.log')}
 if latest is None:
  result.update(verdict='NO_NEW_PRIVATE_CARD_AFTER_8054',latest_private_message_id=None)
  return result
 mid,key,receipt=latest
 decision=load(DEC/(key+'.json'))
 pub=load(PUB/(key+'.json'))
 act=load(ACT)
 if pub is not None and pub.get('draft_id')!=key:
  raise RuntimeError('PUBLIC_RECEIPT_IDENTITY_MISMATCH')
 if decision is not None and decision.get('draft_id')!=key:
  raise RuntimeError('EDITORIAL_RECEIPT_IDENTITY_MISMATCH')
 dts=decision.get('timestamp') if decision is not None else None
 pts=pub.get('published_at') if pub is not None else None
 result.update(
  latest_private_message_id=mid,
  latest_private_draft_id=key,
  latest_decision=decision.get('decision') if decision else 'NOT_SAVED',
  decision_age_min=age(dts),
  public_status=pub.get('status') if pub else 'NO_PUBLIC_RECEIPT',
  public_message_id=pub.get('message_id') if pub and isinstance(pub.get('message_id'),int) else None,
  publication_age_min=age(pts),
  public_channel_id=pub.get('channel_id') if pub else None,
  pub_schedule_ran_after_decision=bool(
   dts is not None and mark(OP/'news_rg_publication_last_launch') is not None
   and mark(OP/'news_rg_publication_last_launch')>=dts),
  verdict=classify(decision,pub,act,receipt,mid),
  autonomy_provenance_note='Receipt proves delivery; launch marker alone cannot distinguish DSM from manual tick.')
 return result

def selftest():
 r={'draft_id':'a'*24,'telegram_photo_file_id':'f'*30}
 accepted={'draft_id':r['draft_id'],'telegram_message_id':8055,
           'decision':'editorially_accepted_not_published','public_publication':'OFF'}
 assert classify(None,None,None,r,8055)=='WAITING_FOR_CALLBACK_DECISION'
 assert classify(accepted,None,{'status':'ACTIVE','chat_id':CHANNEL},r,8055)=='APPROVED_AWAITING_SCHEDULED_PUBLICATION'
 confirmed={'status':'PUBLIC_PUBLISHED_CONFIRMED','channel_id':CHANNEL,'message_id':7876}
 assert classify(accepted,confirmed,{},r,8055)=='PUBLIC_PUBLISHED_CONFIRMED'
 uncertain={'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY'}
 assert classify(accepted,uncertain,{},r,8055)=='PUBLIC_SEND_UNCERTAIN_STOP_NO_RETRY'
 rejected=dict(accepted,decision='editorially_rejected')
 assert classify(rejected,None,{},r,8055)=='HUMAN_REJECTED_NO_PUBLICATION_EXPECTED'
 print('NEWS_RG_LATEST_CARD_AUTONOMY_AUDIT_SELFTEST_PASS')

if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['inspect']:
   print(json.dumps(report(),sort_keys=True,ensure_ascii=False,indent=2))
  else:raise RuntimeError('EXPECTED_SELFTEST_OR_INSPECT')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:120],
    'publications_triggered':0},ensure_ascii=False))
  sys.exit(2)
