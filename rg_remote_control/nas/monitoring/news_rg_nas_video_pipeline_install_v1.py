#!/usr/bin/env python3
"""Install optional NAS-only video pipeline. Does not touch bot, crons, scheduler or publishing."""
import json,os,pathlib,subprocess,sys,tempfile
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
SRC=pathlib.Path('/tmp/news_rg_nas_video_pipeline_v1.py')
DST=ROOT/'news_rg_nas_video_pipeline_v1.py'
def install():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not ROOT.is_dir() or ROOT.is_symlink():raise RuntimeError('ROOT_UNSAFE')
 if SRC.is_symlink() or not SRC.is_file() or SRC.stat().st_size>60000:raise RuntimeError('STAGE_MISSING_OR_UNSAFE')
 data=SRC.read_bytes()
 for cmd in (['/usr/bin/python3','-m','py_compile',str(SRC)],['/usr/bin/python3',str(SRC),'selftest']):
  r=subprocess.run(cmd,capture_output=True,timeout=15)
  if r.returncode!=0:raise RuntimeError('STAGED_TEST_FAILED')
 if DST.is_symlink():raise RuntimeError('DESTINATION_SYMLINK')
 if DST.exists():
  if DST.read_bytes()!=data:raise RuntimeError('DESTINATION_VERSION_CONFLICT')
  return {'status':'ALREADY_INSTALLED','publication':'OFF','scheduler_modified':False}
 fd,temp=tempfile.mkstemp(prefix='.news_rg_nas_',dir=str(ROOT))
 try:
  with os.fdopen(fd,'wb') as h:
   os.fchmod(h.fileno(),0o600);h.write(data);h.flush();os.fsync(h.fileno())
  os.link(temp,DST)
 finally:
  if os.path.exists(temp):os.unlink(temp)
 return {'status':'NAS_VIDEO_PIPELINE_INSTALLED','publication':'OFF','scheduler_modified':False,'telegram_calls':0,'cloudflare_calls':0}
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:print('NEWS_RG_NAS_VIDEO_PIPELINE_INSTALL_SELFTEST_PASS')
  elif sys.argv[1:]==['install']:print(json.dumps(install()))
  else:raise RuntimeError('INVALID_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100] if isinstance(e,RuntimeError) else type(e).__name__,'publication':'OFF'}));sys.exit(2)
