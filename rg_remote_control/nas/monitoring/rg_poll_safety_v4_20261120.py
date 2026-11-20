#!/usr/bin/env python3
"""RG NEWS2 poll v4: add QA at generation/approval and guard BEFORE any public photo."""
import ast,datetime,hashlib,json,os,stat,sys,tempfile
from pathlib import Path
B=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
P=B/'operator/news_rg_poll_moderation_v1.py'
Q=B/'operator/news_rg_poll_quality_v1.py'
BK=B/'rg_news2_fix_20261119/protected_backups'
OLD='abcf4683e9e4629434471acf1c2813100d33febb323b6d9870e325f6c882d782'
QA='bc585371bc693093a5469ca7abc32a09a35a9ebdec67f919223c52a1c05b4e22'
MARK='RG_POLL_SAFETY_V4'
def sha(b):return hashlib.sha256(b).hexdigest()
def change(s):
 if MARK in s:raise ValueError('ALREADY_PATCHED')
 changes=[
 (" return True\ndef make_variant(used,required_event=None):",
  " from news_rg_poll_quality_v1 import validate as poll_quality\n poll_quality(question,options)\n return True\ndef make_variant(used,required_event=None):"),
 ("  if action=='pub':\n   if state.get('publications')!=0:return {'status':'POLL_ALREADY_PUBLISHED'}",
  "  if action=='pub':\n   if state.get('publications')!=0:return {'status':'POLL_ALREADY_PUBLISHED'}\n"
  "   # "+MARK+": QA, no public claim until full route is accepted\n"
  "   try:\n    from news_rg_poll_quality_v1 import validate as poll_quality\n"
  "    poll_quality(v.get('question'),v.get('options'))\n"
  "   except Exception:return {'status':'POLL_EDITORIAL_QA_FAILED_NO_PUBLICATION','publications':0}\n"
  "   return {'status':'POLL_PUBLICATION_PAUSED_NO_PUBLICATION','publications':0}"),
 (" if action=='pub':\n  try:\n   # This method requires the news bot",
  " if action=='pub':\n"
  "  # "+MARK+": secondary gate before send_photo and sendPoll\n"
  "  return {'status':'POLL_PUBLIC_SEND_PAUSED','publications':0}\n"
  "  try:\n   # This method requires the news bot")
 ]
 for old,new in changes:
  if s.count(old)!=1:raise ValueError('SOURCE_ANCHOR_MISMATCH')
  s=s.replace(old,new)
 if s.count("raise RuntimeError('POLL_HUMAN_REVIEW_REQUIRED_NO_SEND')")!=1:
  raise ValueError('ORIGINAL_SENDPOLL_GUARD_MISSING')
 tree=ast.parse(s)
 names=[x.name for x in tree.body if isinstance(x,ast.FunctionDef)]
 if names.count('callback')!=1 or names.count('validate_poll')!=1:
  raise ValueError('FUNCTION_STRUCTURE_CHANGED')
 return s
def atomic(dst,data,mode):
 fd,tmp=tempfile.mkstemp(prefix='.rg_poll_v4_',dir=str(dst.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(dst))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run():
 if os.geteuid()!=0:raise ValueError('SUDO_REQUIRED')
 if any(x.is_symlink() or not x.is_dir() for x in (P.parent,BK)):
  raise ValueError('UNSAFE_DIRECTORY')
 if any(x.is_symlink() or not x.is_file() for x in (P,Q)):
  raise ValueError('UNSAFE_SOURCE')
 raw=P.read_bytes()
 if sha(raw)!=OLD:raise ValueError('POLL_SHA_CHANGED_SAFE_STOP')
 if sha(Q.read_bytes())!=QA:raise ValueError('QA_SHA_CHANGED_SAFE_STOP')
 patched=change(raw.decode('utf8')).encode('utf8')
 mode=stat.S_IMODE(P.stat().st_mode)
 if mode&0o022:raise ValueError('UNSAFE_MODE')
 when=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=BK/('news_rg_poll_moderation_v1.before_v4_'+when+'.py')
 fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
 with os.fdopen(fd,'wb') as f:
  f.write(raw);f.flush();os.fsync(f.fileno())
 try:
  atomic(P,patched,mode)
  if sha(P.read_bytes())!=sha(patched):raise RuntimeError('WRITE_VERIFY_FAILED')
 except Exception:
  atomic(P,raw,mode)
  raise RuntimeError('ROLLED_BACK')
 return {'status':'RG_NEWS2_POLL_SAFETY_V4_STAGED_OFF',
  'old_sha256':sha(raw),'new_sha256':sha(patched),'backup':str(backup),
  'generation_quality_check':True,'moderator_quality_check':True,
  'public_photo_before_poll_blocked':True,
  'publication_enabled':False,'telegram_calls':0,'publications':0,
  'other_modules_changed':0}
def selftest():
 fixture=("def validate_poll(question,options,topic):\n return True\n"
 "def make_variant(used,required_event=None):\n pass\n"
 "def callback(update,cfg):\n"
 " if False:\n"
 "  if action=='pub':\n   if state.get('publications')!=0:return {'status':'POLL_ALREADY_PUBLISHED'}\n"
 " if action=='pub':\n  try:\n   # This method requires the news bot\n"
 "   image_id=send_photo(None)\n"
 "   raise RuntimeError('POLL_HUMAN_REVIEW_REQUIRED_NO_SEND')\n"
 "   res=telegram('sendPoll',{})\n"
 "  except Exception:pass\n")
 patched=change(fixture)
 assert patched.index('POLL_PUBLIC_SEND_PAUSED')<patched.index('image_id=send_photo')
 assert patched.index('POLL_PUBLICATION_PAUSED_NO_PUBLICATION')<patched.index('image_id=send_photo')
 print(json.dumps({'status':'RG_POLL_SAFETY_V4_SELFTEST_PASS','telegram_calls':0,'publications':0}))
if __name__=='__main__':
 try:
  if '--selftest' in sys.argv:selftest()
  else:print(json.dumps(run(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_SAFETY_V4_SAFE_STOP','reason':str(e)[:150],
   'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
