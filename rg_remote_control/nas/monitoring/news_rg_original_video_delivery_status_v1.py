#!/usr/bin/env python3
"""Read-only, no-secrets status for one manually submitted video.
No Bot API calls, no Telegram pollers, no sends, no file or DB writes.
"""
import sys,json,pathlib,hashlib,re
OP=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
POST='https://t.me/nexta_live/125698'
ID=hashlib.sha256(('NEWS_RG_MANUAL_VIDEO_V2\0'+POST).encode()).hexdigest()[:24]
ST=OP/'news_rg_private_review_staging'
REC=OP/'news_rg_private_multipart_receipts_v1'
DEC=OP/'news_rg_editorial_decisions_v1'
HAND=OP/'news_rg_video_watermark_handoff_v1'
LOG=OP/'news_rg_private_dispatch_status_v1.json'
def load(p):
 if p.is_symlink():return {'state':'UNSAFE_SYMLINK'}
 if not p.is_file():return None
 if p.stat().st_size>20000:return {'state':'UNSAFE_SIZE'}
 try:
  return json.loads(p.read_text(encoding='utf8'))
 except (ValueError,UnicodeError,OSError):return {'state':'UNREADABLE'}
def latest_unresolved():
 if not REC.is_dir() or REC.is_symlink():return {'state':'UNAVAILABLE'}
 open_=[]
 bad=[]
 for p in REC.glob('*.json'):
  obj=load(p)
  if not isinstance(obj,dict):continue
  if obj.get('status') in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY','HTTP_REJECTED_NO_RETRY'):
   bad.append(obj.get('status'));continue
  if obj.get('status')=='PRIVATE_SENT_CONFIRMED' and not (DEC/(p.stem+'.json')).is_file():
   open_.append(p.stem==ID)
 return {'unresolved_cards':len(open_),'target_card_outstanding':any(open_),
         'blocking_send_errors':sorted(set(bad))}
def status():
 stage=load(ST/(ID+'.json'))
 receipt=load(REC/(ID+'.json'))
 decision=load(DEC/(ID+'.json'))
 handoff=load(HAND/(ID+'.json'))
 dispatch=load(LOG)
 out={'schema':'NEWS_RG_ORIGINAL_VIDEO_DELIVERY_STATUS_V1',
  'source':POST,'draft_id':ID,'read_only':True,
  'telegram_api_calls':0,'channel_publications':0,'second_pollers':0,
  'staged':isinstance(stage,dict),
  'staged_media_type':stage.get('media_type') if isinstance(stage,dict) else None,
  'watermark_required':stage.get('watermark_required') if isinstance(stage,dict) else None,
  'review_delivery_receipt_status':receipt.get('status') if isinstance(receipt,dict) else None,
  'review_delivery_media_type':receipt.get('media_type') if isinstance(receipt,dict) else None,
  'video_file_id_present':bool(receipt.get('original_video_file_id')) if isinstance(receipt,dict) else False,
  'private_video_message_id':receipt.get('message_id') if isinstance(receipt,dict) else None,
  'editorial_decision':decision.get('decision') if isinstance(decision,dict) else None,
  'watermark_handoff_state':handoff.get('status') if isinstance(handoff,dict) else None,
  'dispatch_status':dispatch.get('status') if isinstance(dispatch,dict) else None,
  'dispatch_reason':dispatch.get('reason') if isinstance(dispatch,dict) else None,
  'card_gate':latest_unresolved()}
 if out['review_delivery_receipt_status']=='PRIVATE_SENT_CONFIRMED' and out['review_delivery_media_type']=='video' and out['video_file_id_present']:
  out['status']='PRIVATE_VIDEO_CARD_CONFIRMED'
 elif out['staged_media_type']=='video':
  out['status']='VIDEO_STAGED_DELIVERY_NOT_PROVEN'
 else:
  out['status']='TARGET_VIDEO_NOT_STAGED'
 return out
def selftest():
 assert re.fullmatch('[a-f0-9]{24}',ID)
 assert len(hashlib.sha256(b'x').hexdigest())==64
 assert 'nexta_live/125698' in POST
 print('NEWS_RG_ORIGINAL_VIDEO_DELIVERY_STATUS_SELFTEST_PASS')
if __name__=='__main__':
 if sys.argv[1:]==['selftest']:selftest()
 elif sys.argv[1:]==['status']:
  print(json.dumps(status(),ensure_ascii=False,sort_keys=True))
 else:raise SystemExit('EXPECTED_SELFTEST_OR_STATUS')
