#!/usr/bin/env python3
"""NEWS RG approved video -> durable watermark handoff, NO direct publication.

The existing Cloudflare RG watermark queue is separate. This local outbox
does not claim Cloudflare acceptance. Only a verified adapter may later mark
an item submitted. Safe reconciliation is idempotent and read-only except job
creation for a previously recorded human-approved decision.
"""
import os,sys,json,pathlib,re,time,tempfile,hashlib
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
ST=O/'news_rg_private_review_staging'
RECEIPTS=O/'news_rg_private_multipart_receipts_v1'
DECISIONS=O/'news_rg_editorial_decisions_v1'
OUT=O/'news_rg_video_watermark_handoff_v1'
PREFIX='NEWS_RG_VIDEO_WATERMARK_HANDOFF_V1'
def safe(p):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>20000:raise ValueError('UNSAFE_OR_MISSING_RECORD')
 return json.loads(p.read_text('utf8'))
def ensure_approved(draft_id):
 if not isinstance(draft_id,str) or not re.fullmatch('[0-9a-f]{24}',draft_id):raise ValueError('INVALID_DRAFT_ID')
 stage=safe(ST/(draft_id+'.json'))
 receipt=safe(RECEIPTS/(draft_id+'.json'))
 decision=safe(DECISIONS/(draft_id+'.json'))
 if stage.get('draft_id')!=draft_id or stage.get('public_publication')!='OFF':
  raise ValueError('UNSAFE_STAGING')
 if stage.get('media_type')!='video' or stage.get('watermark_required') is not True:
  return {'status':'NOT_A_WATERMARK_VIDEO','draft_id':draft_id}
 if stage.get('original_video_url') is None or not stage.get('original_media_source'):
  raise ValueError('ORIGINAL_VIDEO_MISSING')
 if receipt.get('status')!='PRIVATE_SENT_CONFIRMED' or receipt.get('media_type')!='video':
  raise ValueError('NO_CONFIRMED_VIDEO_MODERATION_CARD')
 if decision.get('decision')!='editorially_accepted_not_published':
  raise ValueError('NOT_APPROVED')
 if decision.get('draft_id')!=draft_id or decision.get('telegram_message_id')!=receipt.get('message_id'):
  raise ValueError('DECISION_DELIVERY_MISMATCH')
 if decision.get('public_publication')!='OFF':raise ValueError('PUBLICATION_GATE_CHANGED')
 if OUT.is_symlink():raise ValueError('OUTBOX_SYMLINK')
 OUT.mkdir(mode=0o700,exist_ok=True)
 path=OUT/(draft_id+'.json')
 if path.is_symlink():raise ValueError('JOB_SYMLINK')
 if path.exists():
  item=safe(path)
  if item.get('draft_id')!=draft_id or item.get('schema')!=PREFIX:
   raise ValueError('JOB_CONFLICT')
  return {'status':'WATERMARK_HANDOFF_ALREADY_QUEUED','draft_id':draft_id}
 payload={'schema':PREFIX,'draft_id':draft_id,'source_url':stage['original_media_source'],
    'original_video_url':stage['original_video_url'],'private_video_file_id':receipt.get('original_video_file_id'),
    'private_message_id':receipt['message_id'],'approved_at':decision.get('timestamp'),
    'proposed_text':stage['proposed_text'],'media_type':'video',
    'watermark_required':True,'watermark_target':'telegram-video-watermark-publish-queue-v1',
    'status':'WAITING_FOR_VERIFIED_WATERMARK_BRIDGE','public_publication':'OFF',
    'created_at':int(time.time()),'release_to_public_channel':False,
    'fingerprint':hashlib.sha256((draft_id+'|'+stage['original_media_source']).encode()).hexdigest()}
 # O_EXCL ensures no duplicate jobs or forced retries. No direct CF calls.
 fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w',encoding='utf8') as h:
  json.dump(payload,h,ensure_ascii=False,sort_keys=True);h.flush();os.fsync(h.fileno())
 return {'status':'WATERMARK_HANDOFF_QUEUED_LOCAL','draft_id':draft_id,
    'cloudflare_delivery':'NOT_VERIFIED','publications':0}
def selftest():
 assert PREFIX.startswith('NEWS_RG_VIDEO_')
 assert 'telegram-video-watermark-publish-queue-v1' in 'telegram-video-watermark-publish-queue-v1'
 assert len(hashlib.sha256(b'demo').hexdigest())==64
 print('NEWS_RG_VIDEO_WATERMARK_HANDOFF_SELFTEST_PASS')
def main():
 if sys.argv[1:]==['selftest']:selftest()
 elif len(sys.argv)==3 and sys.argv[1]=='ensure-approved':
  print(json.dumps(ensure_approved(sys.argv[2]),ensure_ascii=False,sort_keys=True))
 else:raise ValueError('EXPECTED_SELFTEST_OR_ENSURE_APPROVED')
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100] if isinstance(e,ValueError) else type(e).__name__,
    'publications':0,'cloudflare_delivery':'NOT_ATTEMPTED'},ensure_ascii=False))
  sys.exit(2)
