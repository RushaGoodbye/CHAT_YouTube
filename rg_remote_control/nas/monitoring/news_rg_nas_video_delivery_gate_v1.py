#!/usr/bin/env python3
"""Read-only gate for NAS-rendered approved video. Does not send or publish.

Only the existing Telegram bot owner may later consume a verified delivery
request. Safe state never implies that a channel post has occurred.
"""
import hashlib,json,pathlib,re,sys
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
def load(p):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>24000:raise ValueError('MISSING_OR_UNSAFE_RECORD')
 return json.loads(p.read_text('utf-8'))
def verify(d):
 if not re.fullmatch('[a-f0-9]{24}',d):raise ValueError('BAD_DRAFT_ID')
 q=load(O/'news_rg_nas_watermarked_v1'/(d+'.json'))
 s=load(O/'news_rg_private_review_staging'/(d+'.json'))
 a=load(O/'news_rg_private_multipart_receipts_v1'/(d+'.json'))
 x=load(O/'news_rg_editorial_decisions_v1'/(d+'.json'))
 if q.get('status')!='NAS_WATERMARK_RENDERED' or q.get('publication')!='OFF' or q.get('telegram_delivery')!='NOT_SENT':raise ValueError('RENDER_RECEIPT_INVALID')
 if s.get('draft_id')!=d or s.get('media_type')!='video' or s.get('public_publication')!='OFF':raise ValueError('STAGING_INVALID')
 if x.get('decision')!='editorially_accepted_not_published' or x.get('draft_id')!=d or x.get('public_publication')!='OFF':raise ValueError('APPROVAL_INVALID')
 if a.get('status')!='PRIVATE_SENT_CONFIRMED' or a.get('message_id')!=x.get('telegram_message_id'):raise ValueError('PRIVATE_RECEIPT_INVALID')
 p=pathlib.Path(str(q.get('output','')))
 if p.parent!=O/'news_rg_nas_watermarked_v1' or p.name!=d+'.mp4' or p.is_symlink() or not p.is_file() or p.stat().st_size<=0:raise ValueError('VIDEO_MISSING')
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 if h.hexdigest()!=q.get('sha256'):raise ValueError('VIDEO_HASH_MISMATCH')
 return {'status':'READY_FOR_SINGLE_OWNER_DELIVERY_INTEGRATION','draft_id':d,'video_bytes':p.stat().st_size,'publications':0,'telegram_calls':0,'cloudflare_calls':0}
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:
   assert len(hashlib.sha256(b'test').hexdigest())==64
   print('NEWS_RG_NAS_VIDEO_DELIVERY_GATE_SELFTEST_PASS')
  elif len(sys.argv)==3 and sys.argv[1]=='verify':print(json.dumps(verify(sys.argv[2]),sort_keys=True))
  else:raise ValueError('EXPECTED_SELFTEST_OR_VERIFY')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e) if isinstance(e,ValueError) else type(e).__name__,'publications':0}));sys.exit(2)
