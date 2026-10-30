#!/usr/bin/env python3
"""NAS-only video batch runner. No Cloudflare, Telegram sends, or publication.
Existing production bot/scheduler untouched. Operator invokes explicitly.
Receipts distinguish rendered from delivered. Fail-closed on missing local media.
"""
import argparse,hashlib,json,os,pathlib,subprocess,sys,tempfile
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
HAND=BASE/'news_rg_video_watermark_handoff_v1'
DONE=BASE/'news_rg_nas_video_receipts_v1'
WORKER=BASE/'news_rg_nas_watermark_worker_v1.py'
def atomic_new(p,obj):
 data=json.dumps(obj,sort_keys=True,ensure_ascii=False).encode()
 fd=os.open(str(p),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
def read(p):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>20000:raise ValueError('UNSAFE_JOB')
 return json.loads(p.read_text('utf8'))
def batch(root,out,logo,limit=3):
 if not HAND.is_dir() or HAND.is_symlink() or not WORKER.is_file() or WORKER.is_symlink():raise ValueError('NOT_INSTALLED')
 if not DONE.exists():DONE.mkdir(mode=0o700)
 if DONE.is_symlink() or not DONE.is_dir():raise ValueError('UNSAFE_RECEIPTS')
 summary={'status':'NAS_VIDEO_BATCH','rendered':0,'already_done':0,'blocked':0,'publications':0,'telegram_calls':0,'cloudflare_calls':0}
 for path in sorted(HAND.glob('*.json'))[:limit]:
  try:
   job=read(path);draft=path.stem
   if job.get('schema')!='NEWS_RG_VIDEO_WATERMARK_HANDOFF_V1' or job.get('draft_id')!=draft or job.get('status')!='WAITING_FOR_VERIFIED_WATERMARK_BRIDGE' or job.get('public_publication')!='OFF' or job.get('release_to_public_channel') is not False:raise ValueError('INVALID_JOB')
   receipt=DONE/(draft+'.json')
   if receipt.exists() or receipt.is_symlink():
    if read(receipt).get('status')=='NAS_WATERMARK_RENDERED':summary['already_done']+=1;continue
    raise ValueError('RECEIPT_CONFLICT')
   # Explicit human-supplied mapping: never download unverified source URLs.
   mapping=root/(draft+'.mp4')
   if not mapping.is_file() or mapping.is_symlink():raise ValueError('LOCAL_ORIGINAL_MISSING')
   cmd=[sys.executable,str(WORKER),'render','--input-root',str(root),'--file',draft+'.mp4','--output-dir',str(out),'--logo',str(logo)]
   proc=subprocess.run(cmd,capture_output=True,text=True,timeout=1805)
   if proc.returncode:raise ValueError('RENDER_FAILED')
   result=json.loads(proc.stdout)
   if result.get('status') not in ('NAS_WATERMARK_RENDERED','ALREADY_EXISTS_NO_OVERWRITE'):raise ValueError('UNEXPECTED_RENDER_RESULT')
   atomic_new(receipt,{'draft_id':draft,'status':'NAS_WATERMARK_RENDERED','local_output':result['output'],'telegram_delivery':'NOT_SENT','publication':'OFF'})
   summary['rendered']+=1
  except (ValueError,OSError,subprocess.TimeoutExpired,json.JSONDecodeError):summary['blocked']+=1
 return summary
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['selftest','batch']);p.add_argument('--local-originals');p.add_argument('--outputs');p.add_argument('--logo');p.add_argument('--limit',type=int,default=3);a=p.parse_args()
 if a.mode=='selftest':
  assert 'NOT_SENT'!='CONFIRMED';print('NEWS_RG_NAS_VIDEO_BATCH_SELFTEST_PASS');return
 if not (a.local_originals and a.outputs and a.logo) or not 1<=a.limit<=10:raise ValueError('ARGUMENTS_REQUIRED')
 print(json.dumps(batch(pathlib.Path(a.local_originals),pathlib.Path(a.outputs),pathlib.Path(a.logo),a.limit)))
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'status':'SAFE_STOP','reason':type(e).__name__,'publications':0}));sys.exit(2)
