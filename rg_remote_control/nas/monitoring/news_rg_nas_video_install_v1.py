#!/usr/bin/env python3
"""Install NAS-only video rendering modules from staged files, no bot/cron edits."""
import hashlib,json,os,pathlib,subprocess,sys,tempfile
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
MODULES={'news_rg_nas_watermark_worker_v1.py':'/tmp/news_rg_nas_watermark_worker_v1.py','news_rg_nas_video_batch_v1.py':'/tmp/news_rg_nas_video_batch_v1.py'}
def run():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink():raise RuntimeError('OPERATOR_MISSING')
 staged={}
 for name,src in MODULES.items():
  p=pathlib.Path(src);dest=O/name
  if p.is_symlink() or not p.is_file() or p.stat().st_size>50000:raise RuntimeError('STAGE_UNSAFE')
  if dest.is_symlink():raise RuntimeError('TARGET_SYMLINK')
  b=p.read_bytes()
  if dest.exists() and dest.read_bytes()!=b:raise RuntimeError('TARGET_VERSION_CONFLICT')
  t=subprocess.run(['/usr/bin/python3',str(p),'selftest'],capture_output=True,text=True,timeout=15)
  if t.returncode or 'SELFTEST_PASS' not in t.stdout:raise RuntimeError('SELFTEST_FAILED_'+name)
  staged[name]=b
 installed=[]
 try:
  for name,b in staged.items():
   dest=O/name
   if dest.exists():continue
   fd,tmp=tempfile.mkstemp(dir=str(O),prefix='.rg_nas_video_')
   try:
    with os.fdopen(fd,'wb') as f:
     os.fchmod(f.fileno(),0o600);f.write(b);f.flush();os.fsync(f.fileno())
    os.link(tmp,dest)
    installed.append(dest)
   finally:
    if os.path.exists(tmp):os.unlink(tmp)
  return {'status':'NAS_VIDEO_MODULES_INSTALLED','count':len(staged),'new_files':len(installed),'publications':0,'telegram_calls':0,'cloudflare_calls':0,'bot_or_schedule_modified':False}
 except Exception:
  for d in reversed(installed):
   if d.is_file() and not d.is_symlink() and d.read_bytes()==staged[d.name]:d.unlink()
  raise
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:print('NEWS_RG_NAS_VIDEO_INSTALL_SELFTEST_PASS')
  elif sys.argv[1:]==['install']:print(json.dumps(run()))
  else:raise RuntimeError('INVALID_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:120] if isinstance(e,RuntimeError) else type(e).__name__,'publications':0}))
  sys.exit(2)
