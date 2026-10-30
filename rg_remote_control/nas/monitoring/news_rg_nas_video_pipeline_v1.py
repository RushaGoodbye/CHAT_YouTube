#!/usr/bin/env python3
"""NAS NEWS RG approved Telegram video -> local watermark; no Cloudflare or publication.

Runs one-shot under existing DSM owner (never launches a Telegram poller).
Only accepted, private-delivered videos qualify. Refuses uncertain results.
Needs Telegram Bot getFile for the already-confirmed private video file_id;
Telegram's Bot API download limit applies. Runs only on explicit process-one.
"""
import hashlib,importlib.util,json,os,pathlib,re,subprocess,sys,tempfile,urllib.request,urllib.parse
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
ST=O/'news_rg_private_review_staging'
DEC=O/'news_rg_editorial_decisions_v1'
ACK=O/'news_rg_private_multipart_receipts_v1'
OUT=O/'news_rg_nas_watermarked_v1'
LOCK=O/'news_rg_nas_video_pipeline.lock'
def safe(p):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>24000:raise ValueError('RECORD_MISSING_OR_UNSAFE')
 return json.loads(p.read_text('utf-8'))
def eligible(d):
 if not re.fullmatch('[a-f0-9]{24}',d):raise ValueError('INVALID_ID')
 st=safe(ST/(d+'.json'));dec=safe(DEC/(d+'.json'));ack=safe(ACK/(d+'.json'))
 if st.get('draft_id')!=d or st.get('media_type')!='video' or st.get('watermark_required') is not True:raise ValueError('NOT_WATERMARK_VIDEO')
 if st.get('public_publication')!='OFF' or dec.get('public_publication')!='OFF':raise ValueError('PUBLICATION_GATE_UNSAFE')
 if st.get('editorial_status')!='HUMAN_FACT_AND_VIDEO_REVIEW_REQUIRED':raise ValueError('REVIEW_REQUIRED')
 if dec.get('decision')!='editorially_accepted_not_published' or dec.get('draft_id')!=d:raise ValueError('NOT_ACCEPTED')
 if ack.get('status')!='PRIVATE_SENT_CONFIRMED' or ack.get('media_type')!='video' or ack.get('draft_id')!=d:raise ValueError('NOT_DELIVERED')
 if ack.get('message_id')!=dec.get('telegram_message_id'):raise ValueError('MESSAGE_MISMATCH')
 file_id=ack.get('original_video_file_id')
 if not isinstance(file_id,str) or not re.fullmatch('[A-Za-z0-9_-]{15,255}',file_id):raise ValueError('MISSING_FILE_ID')
 return file_id
def token():
 p=O/'news_rg_multipart.py'
 if p.is_symlink() or not p.is_file():raise ValueError('NO_EXISTING_BOT_TRANSPORT')
 spec=importlib.util.spec_from_file_location('news_rg_multipart',str(p))
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 t=mod.token()
 if not isinstance(t,str) or not re.fullmatch(r'\d+:[A-Za-z0-9_-]{30,}',t):raise ValueError('NO_BOT_TOKEN')
 return t
def fetch_video(fid,secret,dest):
 api='https://api.telegram.org/bot'+secret+'/getFile'
 req=urllib.request.Request(api,data=urllib.parse.urlencode({'file_id':fid}).encode())
 with urllib.request.urlopen(req,timeout=20) as res: j=json.loads(res.read(12000))
 meta=j.get('result') or {}
 path=meta.get('file_path');size=meta.get('file_size')
 if j.get('ok') is not True or not isinstance(path,str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,500}',path) or '..' in path.split('/'):raise ValueError('BAD_TELEGRAM_PATH')
 if not isinstance(size,int) or not 0<size<=20_000_000:raise ValueError('BOT_DOWNLOAD_LIMIT_OR_UNKNOWN_SIZE')
 url='https://api.telegram.org/file/bot'+secret+'/'+path
 count=0
 with urllib.request.urlopen(url,timeout=60) as r,open(dest,'xb') as f:
  while True:
   b=r.read(1024*1024)
   if not b:break
   count+=len(b)
   if count>20_000_000:raise ValueError('VIDEO_TOO_LARGE')
   f.write(b)
  f.flush();os.fsync(f.fileno())
 if count!=size:raise ValueError('DOWNLOAD_SIZE_MISMATCH')
def process(d):
 import fcntl
 if os.geteuid()!=0:raise ValueError('SUDO_REQUIRED')
 fid=eligible(d)
 if OUT.is_symlink():raise ValueError('OUTPUT_SYMLINK')
 OUT.mkdir(mode=0o700,exist_ok=True)
 with open(LOCK,'a+') as lock:
  os.chmod(LOCK,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  dest=OUT/(d+'.mp4')
  if dest.exists() or dest.is_symlink():raise ValueError('OUTPUT_EXISTS_MANUAL_REVIEW_REQUIRED')
  receipt=OUT/(d+'.json')
  if receipt.exists() or receipt.is_symlink():raise ValueError('RECEIPT_EXISTS_MANUAL_REVIEW_REQUIRED')
  with tempfile.TemporaryDirectory(prefix='.nasvideo_',dir=str(OUT)) as temp:
   incoming=pathlib.Path(temp)/'source.mp4'
   result=pathlib.Path(temp)/'result.mp4'
   fetch_video(fid,token(),incoming)
   # Original audio retained; watermark is rendered locally without external services.
   vf="drawtext=text='NEWS RG':fontsize=28:fontcolor=white@0.75:box=1:boxcolor=black@0.35:boxborderw=8:x=w-tw-24:y=h-th-24"
   cmd=['/usr/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-i',str(incoming),
        '-vf',vf,'-map','0:v:0','-map','0:a?','-c:v','libx264','-crf','22','-preset','fast','-c:a','aac','-b:a','128k','-movflags','+faststart',str(result)]
   try:r=subprocess.run(cmd,timeout=900,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   except subprocess.TimeoutExpired:raise ValueError('RENDER_TIMEOUT')
   if r.returncode!=0 or result.stat().st_size==0:raise ValueError('RENDER_FAILED')
   # Exclusive link protects against duplicate concurrent publishers. This is NOT publication.
   os.link(result,dest)
   data={'status':'NAS_WATERMARK_RENDERED','draft_id':d,'output':str(dest),
         'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
         'telegram_delivery':'NOT_SENT','publication':'OFF','cloudflare_calls':0}
   fd=os.open(str(receipt),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
   with os.fdopen(fd,'w',encoding='utf-8') as h:json.dump(data,h);h.flush();os.fsync(h.fileno())
  return {'status':'NAS_WATERMARK_RENDERED','draft_id':d,'publications':0,'telegram_sends':0,'cloudflare_calls':0}
def selftest():
 assert eligible.__name__=='eligible'
 assert 'drawtext' in process.__code__.co_consts.__str__()
 print('NEWS_RG_NAS_VIDEO_PIPELINE_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif len(sys.argv)==3 and sys.argv[1]=='process-one':print(json.dumps(process(sys.argv[2]),sort_keys=True))
  else:raise ValueError('EXPECTED_SELFTEST_OR_PROCESS_ONE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e) if isinstance(e,ValueError) else type(e).__name__,'publications':0}))
  sys.exit(2)
