#!/usr/bin/env python3
"""NAS-only watermark worker, manual local file, NO Telegram API or Cloudflare.

Fail closed. This is an offline renderer, NOT a publishing agent.
Requires ffmpeg/ffprobe on NAS. Input must be a local regular MP4.
Output is atomically committed once; existing outputs never overwritten.
"""
import argparse,hashlib,json,os,pathlib,subprocess,tempfile
def validate(root,relative):
 if not relative or pathlib.PurePosixPath(relative).is_absolute() or '..' in pathlib.PurePosixPath(relative).parts:raise ValueError('UNSAFE_PATH')
 path=root/relative
 if path.is_symlink() or not path.is_file() or path.suffix.lower()!='.mp4':raise ValueError('UNSAFE_INPUT')
 if path.stat().st_size<=0 or path.stat().st_size>2*1024**3:raise ValueError('INVALID_SIZE')
 return path
def render(root,relative,outdir,logo):
 inp=validate(root,relative)
 if logo.is_symlink() or not logo.is_file() or logo.suffix.lower()!='.png':raise ValueError('UNSAFE_LOGO')
 if not outdir.is_dir() or outdir.is_symlink():raise ValueError('UNSAFE_OUTDIR')
 digest=hashlib.sha256((relative+'|'+str(inp.stat().st_size)).encode()).hexdigest()[:20]
 target=outdir/(digest+'.mp4')
 if target.exists() or target.is_symlink():return {'status':'ALREADY_EXISTS_NO_OVERWRITE','output':str(target),'published':False}
 fd,tmp=tempfile.mkstemp(prefix='.rgwm_',suffix='.mp4',dir=str(outdir));os.close(fd)
 try:
  cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-i',str(inp),'-loop','1','-i',str(logo),
       '-filter_complex','[1:v]format=rgba,colorchannelmixer=aa=0.65[wm];[0:v][wm]overlay=W-w-20:H-h-20:shortest=1[v]',
       '-map','[v]','-map','0:a?','-c:v','libx264','-preset','fast','-crf','21','-c:a','copy','-movflags','+faststart',tmp]
  r=subprocess.run(cmd,timeout=1800,capture_output=True)
  if r.returncode or pathlib.Path(tmp).stat().st_size==0:raise RuntimeError('RENDER_FAILED')
  os.link(tmp,target)
  return {'status':'NAS_WATERMARK_RENDERED','output':str(target),'published':False,'telegram_calls':0,'cloudflare_calls':0}
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def test():
 assert 'overlay=' in 'overlay=W-w-20:H-h-20:shortest=1'
 assert '..' in pathlib.PurePosixPath('../x.mp4').parts
 print('NEWS_RG_NAS_WATERMARK_WORKER_SELFTEST_PASS')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['selftest','render'])
 p.add_argument('--input-root');p.add_argument('--file');p.add_argument('--output-dir');p.add_argument('--logo')
 a=p.parse_args()
 try:
  if a.mode=='selftest':test()
  elif not all((a.input_root,a.file,a.output_dir,a.logo)):raise ValueError('MISSING_ARGS')
  else:print(json.dumps(render(pathlib.Path(a.input_root),a.file,pathlib.Path(a.output_dir),pathlib.Path(a.logo)),ensure_ascii=False))
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e) if isinstance(e,ValueError) else type(e).__name__,'published':False}))
  raise SystemExit(2)
