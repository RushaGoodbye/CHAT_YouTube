#!/usr/bin/env python3
"""NEWS RG NAS video publisher, reuses photo publisher activation, lock and receipts.
No getUpdates, no new schedules. Only confirmed watermark MP4 and live Accept.
"""
import os,sys,json,re,pathlib,time,hashlib,uuid,urllib.request,urllib.error,fcntl,importlib.util
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
PUB=O/'news_rg_approved_publication_v1.py'
OUT=O/'news_rg_nas_watermarked_v1'
def base():
 spec=importlib.util.spec_from_file_location('newsrg_photo_publisher',str(PUB))
 p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p);return p
def choose(p,act):
 now=int(time.time())
 if not OUT.is_dir() or OUT.is_symlink():return None
 for fp in (p.DEC,p.SENT,p.STAGED,p.PUB):
  if not fp.is_dir() or fp.is_symlink():raise RuntimeError('LEDGER_DIRECTORY_UNSAFE')
 for rp in p.PUB.glob('*.json'):
  if p.read_json(rp).get('status')=='PUBLIC_SEND_UNCERTAIN_NO_RETRY':raise RuntimeError('UNCERTAIN_PUBLIC_SEND_PAUSE')
 ready=[]
 for recpath in p.DEC.glob('*.json'):
  key=recpath.stem
  if not re.fullmatch('[0-9a-f]{24}',key) or recpath.is_symlink():continue
  d=p.read_json(recpath)
  if d.get('draft_id')!=key or d.get('schema')!='NEWS_RG_HUMAN_EDITORIAL_DECISION_V1' or d.get('decision')!='editorially_accepted_not_published' or d.get('public_publication')!='OFF':continue
  when=d.get('timestamp')
  if type(when)!=int or when<=act['activated_at'] or when>now+60 or now-when>86400:continue
  if (p.PUB/(key+'.json')).exists() or (p.PUB/(key+'.json')).is_symlink():continue
  s=p.read_json(p.STAGED/(key+'.json'))
  a=p.read_json(p.SENT/(key+'.json'))
  if s.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1' or s.get('draft_id')!=key or s.get('media_type')!='video' or s.get('watermark_required') is not True:continue
  if s.get('editorial_status')!='HUMAN_FACT_AND_VIDEO_REVIEW_REQUIRED' or s.get('public_publication')!='OFF':continue
  if a.get('status')!='PRIVATE_SENT_CONFIRMED' or a.get('draft_id')!=key or a.get('media_type')!='video' or a.get('message_id')!=d.get('telegram_message_id') or a.get('public_publication')!='OFF':continue
  text=str(s.get('proposed_text','')).strip()
  if not 60<=len(text)<=900 or any(x in text for x in 'ыъэёЫЪЭЁ') or 'НЕВДАЛО' in text.upper():continue
  receipt=OUT/(key+'.json');video=OUT/(key+'.mp4')
  if not receipt.is_file() or receipt.is_symlink() or not video.is_file() or video.is_symlink():continue
  r=p.read_json(receipt)
  if r.get('status')!='NAS_WATERMARK_RENDERED' or r.get('draft_id')!=key or r.get('telegram_delivery')!='NOT_SENT' or r.get('publication')!='OFF' or r.get('output')!=str(video):continue
  if not isinstance(r.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',r['sha256']):continue
  size=video.stat().st_size
  if size<1000 or size>49*1024*1024:continue
  ready.append((when,key,str(video),r['sha256'],text))
 ready.sort()
 return ready[0] if ready else None
def send_mp4(token,channel,video,caption):
 path=pathlib.Path(video)
 raw=path.read_bytes()
 boundary='RGV'+uuid.uuid4().hex
 data=[]
 def field(name,value):
  data.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"\r\n\r\n'+str(value)+'\r\n').encode('utf8'))
 field('chat_id',channel);field('caption',caption);field('supports_streaming','true')
 data.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="video"; filename="news_rg.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode()+raw+b'\r\n')
 data.append(('--'+boundary+'--\r\n').encode())
 req=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendVideo',data=b''.join(data),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
 with urllib.request.urlopen(req,timeout=120) as res: reply=json.loads(res.read(100000))
 if reply.get('ok') is not True or not isinstance(reply.get('result'),dict):raise RuntimeError('VIDEO_SEND_ACK_INVALID')
 return reply['result']
def publish():
 p=base()
 fd=os.open(str(p.LCK),os.O_CREAT|os.O_RDWR,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX)
  act=p.gate()
  selected=choose(p,act)
  if not selected:return {'status':'NO_APPROVED_RENDERED_VIDEO','publications':0}
  when,key,video,expected,caption=selected
  h=hashlib.sha256()
  with open(video,'rb') as f:
   for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
  if h.hexdigest()!=expected:raise RuntimeError('WATERMARK_VIDEO_SHA256_MISMATCH')
  with open(video,'rb') as f:
   if f.read(12)[4:8]!=b'ftyp':raise RuntimeError('WATERMARK_VIDEO_NOT_MP4')
  cfg=p.module();token=p.credentials();channel=p.verify_channel(cfg,token)
  if act['chat_id']!=channel['chat_id'] or act['bot_id']!=channel['bot_id']:raise RuntimeError('CHANNEL_IDENTITY_CHANGED')
  claim=p.PUB/(key+'.json')
  if claim.exists() or claim.is_symlink():raise RuntimeError('ALREADY_CLAIMED')
  p.persist(claim,{'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY','draft_id':key,'channel_id':act['chat_id'],'claimed_at':int(time.time()),'decision_timestamp':when,'media_type':'video','sha256':expected},exclusive=True)
  try:
   result=send_mp4(token,act['chat_id'],video,caption)
   if type(result.get('message_id'))!=int or int((result.get('chat') or {}).get('id',0))!=act['chat_id']:raise RuntimeError('VIDEO_ACK_DESTINATION_MISMATCH')
   p.persist(claim,{'status':'PUBLIC_PUBLISHED_CONFIRMED','draft_id':key,'channel_id':act['chat_id'],'message_id':result['message_id'],'published_at':int(time.time()),'decision_timestamp':when,'media_type':'video','sha256':expected})
   return {'status':'PUBLIC_PUBLISHED_CONFIRMED','draft_id':key,'message_id':result['message_id'],'media_type':'video','publications':1}
  except Exception:
   return {'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY','draft_id':key,'publications_confirmed':0,'automatic_retry':False}
 finally:os.close(fd)
def status():
 p=base();act=p.gate();item=choose(p,act)
 return {'status':'VIDEO_PUBLISHER_ARMED','approved_rendered_video_ready':bool(item),'publications':0}
def selftest():
 assert send_mp4.__name__=='send_mp4'
 assert any('sendVideo' in str(x) for x in send_mp4.__code__.co_consts)
 assert 'getUpdates(' not in open(__file__,encoding='utf8').read().split('def selftest():',1)[0]
 print('NEWS_RG_VIDEO_PUBLISHER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['status']:print(json.dumps(status(),sort_keys=True))
  elif sys.argv[1:]==['publish-one']:
   if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
   print(json.dumps(publish(),sort_keys=True))
  else:raise RuntimeError('INVALID_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100],'publications':0}));sys.exit(2)
