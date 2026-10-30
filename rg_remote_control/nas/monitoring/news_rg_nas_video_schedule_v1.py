#!/usr/bin/env python3
"""NEWS RG: at most one approved video render per existing DSM tick.
No Telegram update polling, no Cloudflare, no public send, fail closed.
"""
import fcntl,json,os,pathlib,re,subprocess,sys,time
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
PIPE=O/'news_rg_nas_video_pipeline_v1.py'
ST=O/'news_rg_private_review_staging'
DEC=O/'news_rg_editorial_decisions_v1'
ACK=O/'news_rg_private_multipart_receipts_v1'
OUT=O/'news_rg_nas_watermarked_v1'
LOCK=O/'news_rg_nas_video_schedule.lock'
def safe(p):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>24000:return {}
 try:return json.loads(p.read_text('utf8'))
 except (ValueError,OSError,UnicodeError):return {}
def candidates():
 if any(not p.is_dir() or p.is_symlink() for p in (ST,DEC,ACK)):return []
 found=[]
 for p in DEC.glob('*.json'):
  d=p.stem
  if not re.fullmatch('[a-f0-9]{24}',d):continue
  x=safe(p);s=safe(ST/(d+'.json'));a=safe(ACK/(d+'.json'))
  if x.get('decision')!='editorially_accepted_not_published' or x.get('draft_id')!=d or x.get('public_publication')!='OFF':continue
  if s.get('media_type')!='video' or s.get('watermark_required') is not True or s.get('public_publication')!='OFF':continue
  if a.get('status')!='PRIVATE_SENT_CONFIRMED' or a.get('media_type')!='video' or a.get('message_id')!=x.get('telegram_message_id'):continue
  if not a.get('original_video_file_id'):continue
  if (OUT/(d+'.mp4')).exists() or (OUT/(d+'.json')).exists():continue
  found.append((x.get('timestamp',0),d))
 return [d for _,d in sorted(found)[:1]]
def tick():
 if os.geteuid()!=0:raise ValueError('SUDO_REQUIRED')
 if PIPE.is_symlink() or not PIPE.is_file():raise ValueError('PIPELINE_NOT_INSTALLED')
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return {'status':'BUSY'}
  for d in candidates():
   try:r=subprocess.run(['/usr/bin/python3',str(PIPE),'process-one',d],capture_output=True,text=True,timeout=930)
   except subprocess.TimeoutExpired:return {'status':'RENDER_TIMEOUT_SAFE_STOP'}
   if r.returncode:return {'status':'RENDER_FAILED_SAFE_STOP'}
   return {'status':'RENDER_INVOKED','draft_id':d,'publications':0}
  return {'status':'NO_APPROVED_VIDEO','publications':0}
 finally:os.close(fd)
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:
   assert len('a'*24)==24
   print('NEWS_RG_NAS_VIDEO_SCHEDULE_SELFTEST_PASS')
  elif sys.argv[1:]==['tick']:print(json.dumps(tick(),sort_keys=True))
  else:raise ValueError('EXPECTED_SELFTEST_OR_TICK')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e) if isinstance(e,ValueError) else type(e).__name__,'publications':0}));sys.exit(2)
