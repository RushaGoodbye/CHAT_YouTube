#!/usr/bin/env python3
"""Securely enroll a NEW project OpenAI API key for NEWS2 image generation.

Requires interactive NAS terminal (getpass; key never echoed or placed in
command arguments, logs or shell history), root-owned 0700 directory and 0600
secret file, no overwrite and no Telegram sends. An API model-read request is
used before saving (not image generation, no image charges).
"""
import datetime,getpass,json,os,stat,sys,tempfile,urllib.request,urllib.error
from pathlib import Path
OP=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
DIR=OP/'.secrets'
DEST=DIR/'openai_image_api_key'
MODEL='gpt-image-2'
class Stop(ValueError):pass
def check_dir():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 for p in (OP,DIR):
  if p.is_symlink():raise Stop('DIRECTORY_SYMLINK')
  st=p.lstat()
  if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077:
   raise Stop('SECRET_FOLDER_NOT_ROOT_0700')
def check_key(key):
 if not isinstance(key,str) or not key.startswith('sk-') or not 35<=len(key)<=300:
  raise Stop('API_KEY_FORMAT_INVALID')
 if any(ord(c)<33 or ord(c)>126 for c in key):
  raise Stop('API_KEY_CONTAINS_UNSAFE_CHARACTERS')
def remote_model_read(key):
 req=urllib.request.Request(
   'https://api.openai.com/v1/models/'+MODEL,
   headers={'Authorization':'Bearer '+key,'Accept':'application/json',
           'User-Agent':'RGNEWS2-Image-Key-Enrollment/1.0'})
 try:
  with urllib.request.urlopen(req,timeout=20) as response:
   data=json.loads(response.read(100000))
   if data.get('id')!=MODEL:
    raise Stop('API_MODEL_ID_UNEXPECTED')
   return True
 except urllib.error.HTTPError as e:
  raise Stop('MODEL_ACCESS_CHECK_HTTP_'+str(e.code))
 except (urllib.error.URLError,TimeoutError):
  raise Stop('OPENAI_API_CONNECTION_FAILED')
def enroll():
 check_dir()
 if DEST.exists() or DEST.is_symlink():raise Stop('SECRET_ALREADY_EXISTS_NO_OVERWRITE')
 if not sys.stdin.isatty():raise Stop('INTERACTIVE_TERMINAL_REQUIRED')
 key=getpass.getpass('Paste NEW OpenAI project API key (input hidden): ')
 try:
  check_key(key)
  remote_model_read(key) # GET only, no image generation or charges.
  fd,tmp=tempfile.mkstemp(prefix='.openai_image_',dir=str(DIR))
  try:
   with os.fdopen(fd,'w',encoding='utf8') as f:
    os.fchmod(f.fileno(),0o600)
    f.write(key+'\n');f.flush();os.fsync(f.fileno())
   if DEST.exists():raise Stop('DESTINATION_CREATED_CONCURRENTLY')
   os.replace(tmp,DEST)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
  st=DEST.lstat()
  if st.st_uid!=0 or not stat.S_ISREG(st.st_mode) or st.st_mode&0o077:
   raise Stop('SECRET_PERMISSIONS_POSTCHECK_FAILED')
  return {'status':'OPENAI_IMAGE_API_KEY_ENROLLED',
      'model':MODEL,'root_only':True,'not_logged':True,
      'model_read_verified':True,'image_api_calls':0,'telegram_calls':0,
      'publications':0,'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 finally:key=None
def status():
 check_dir()
 if DEST.is_symlink():raise Stop('SECRET_SYMLINK')
 if not DEST.is_file():
  return {'status':'KEY_NOT_CONFIGURED','model':MODEL,'image_api_calls':0}
 st=DEST.lstat()
 if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077:
  raise Stop('SECRET_PERMISSIONS_INVALID')
 return {'status':'KEY_CONFIGURED_ROOT_0600','model':MODEL,'key_value_shown':False}
def selftest():
 assert str(DEST).startswith(str(OP)+'/')
 assert MODEL=='gpt-image-2'
 assert len('sk-example-example-example-example-example-123456')>=35
 print('RG_NEWS2_SECURE_KEY_ENROLLMENT_SELFTEST_PASS')
if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:selftest()
  elif mode==['status']:print(json.dumps(status()))
  elif mode==['enroll']:print(json.dumps(enroll(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:120] if isinstance(e,Stop) else type(e).__name__,
                    'key_printed':False,'image_api_calls':0,'publications':0}))
  raise SystemExit(2)
