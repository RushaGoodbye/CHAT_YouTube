#!/usr/bin/env python3
"""Fail-closed read-only verifier for NEWS RG watermark handoff. No external calls."""
import argparse,hashlib,json,pathlib,re
PREFIX='NEWS_RG_VIDEO_WATERMARK_HANDOFF_V1'
TARGET='telegram-video-watermark-publish-queue-v1'
def check(j):
 if not isinstance(j,dict) or j.get('schema')!=PREFIX:return 'INVALID_SCHEMA'
 d=j.get('draft_id')
 if not isinstance(d,str) or not re.fullmatch('[a-f0-9]{24}',d):return 'INVALID_ID'
 if j.get('media_type')!='video' or j.get('watermark_required') is not True:return 'INVALID_MEDIA'
 if j.get('watermark_target')!=TARGET:return 'INVALID_TARGET'
 if j.get('status')!='WAITING_FOR_VERIFIED_WATERMARK_BRIDGE':return 'INVALID_STATE'
 if j.get('public_publication')!='OFF' or j.get('release_to_public_channel') is not False:return 'PUBLICATION_NOT_OFF'
 u=j.get('source_url')
 if not isinstance(u,str) or not u.startswith('https://') or len(u)>4096:return 'INVALID_URL'
 if j.get('fingerprint')!=hashlib.sha256((d+'|'+u).encode()).hexdigest():return 'FINGERPRINT_MISMATCH'
 if not isinstance(j.get('private_message_id'),int) or j['private_message_id']<=0:return 'NO_PRIVATE_ACK'
 return 'VERIFIED_LOCAL_HANDOFF_ONLY'
def inspect(p):
 f=pathlib.Path(p)
 if f.is_symlink() or not f.is_file() or f.stat().st_size>20000:return {'status':'SAFE_STOP','reason':'UNSAFE_FILE'}
 try:j=json.loads(f.read_text(encoding='utf8'))
 except (ValueError,UnicodeError,OSError):return {'status':'SAFE_STOP','reason':'UNREADABLE'}
 return {'status':check(j),'cloudflare_acceptance':'NOT_PROVEN','publications':0,'telegram_calls':0}
def test():
 d='0123456789abcdef01234567';u='https://example.org/video.mp4'
 j={'schema':PREFIX,'draft_id':d,'media_type':'video','watermark_required':True,
 'watermark_target':TARGET,'status':'WAITING_FOR_VERIFIED_WATERMARK_BRIDGE',
 'public_publication':'OFF','release_to_public_channel':False,'source_url':u,
 'fingerprint':hashlib.sha256((d+'|'+u).encode()).hexdigest(),'private_message_id':1}
 assert check(j)=='VERIFIED_LOCAL_HANDOFF_ONLY'
 for k,v in [('public_publication','ON'),('fingerprint','0'*64),('status','SUBMITTED'),('release_to_public_channel',True)]:
  x=dict(j);x[k]=v;assert check(x)!='VERIFIED_LOCAL_HANDOFF_ONLY'
 print('NEWS_RG_WATERMARK_BRIDGE_GUARD_SELFTEST_PASS')
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('mode',choices=('selftest','inspect'));a.add_argument('file',nargs='?');z=a.parse_args()
 if z.mode=='selftest':test()
 elif z.file:print(json.dumps(inspect(z.file),sort_keys=True))
 else:a.error('inspect requires file')
