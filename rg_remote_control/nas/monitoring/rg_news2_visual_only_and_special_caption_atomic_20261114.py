#!/usr/bin/env python3
"""NEWS2 media-only moderation & special-post captions, Nov14 fixed-source release.

Atomic local NAS changes under existing stable guard and sender locks:
- all private moderation cards REQUIRE real photo/video (no text sends)
- Kyiv alert shadow caption and 09:00 memorial caption omit promotional footer
- re-pin whole 18-file guarded LKG to prevent rollback of sender change

DOES NOT send Telegram messages, poll, publish, generate images or change history.
OpenAI image generation integration requires a separately configured image backend:
text-only candidates remain staged, not delivered. Generative images cannot be
passed as source photographs and must disclose AI illustration provenance.
"""
import datetime,fcntl,hashlib,io,json,os,stat,subprocess,sys,tarfile,tempfile,time
from pathlib import Path

BASE=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=BASE/'operator'
R=O/'news_rg_stability_releases_v1'
PIN=R/'pinned_release_v1.json'
SENDER=O/'news_rg_durable_private_sender_v1.py'
MINUTE=Path('/volume1/docker/RG_ALERTS_DEPLOY/nas-minute-silence-v1/rg_minute_silence_nas_v1.py')
ALERT=Path('/volume1/docker/RG_ALERTS_DEPLOY/nas-air-alert-staging/rg_air_alert_v2.py')
OLD_HASH={
 str(SENDER):'261d96d853203fb7b2c929e1961a2f900802abcd89e7667ca53551d69765844d',
 str(MINUTE):'a7135a934fdb0ffa290a94f1237f0a862dd0aaa8deb3ba5add397a77b6e8c397',
 str(ALERT):'c6db486476693fd74621501d0aaaed957b252981de1a6a32c9b1b90a582a13be',
}
VERSION='2026-11-14-stable5.3-health-monitor'
NEXT='2026-11-14-stable5.4-visual-only-moderation'
KEY=('news_rg_manual_link_intake_v1.py','news_rg_editorial_callbacks_v1.py',
 'news_rg_approved_text_publication_v1.py','news_rg_durable_private_sender_v1.py',
 'news_rg_durable_private_dispatch_v1.py','news_rg_stability_healthcheck_v1.py',
 'news_rg_continuous_callback_v1.py','news_rg_publication_schedule_v1.py',
 'news_rg_editorial_rank_v1.py','news_rg_nas_video_pipeline_v1.py',
 'news_rg_stable5_operational_gate_v1.py','news_rg_autonomous_health_v1.py',
 'news_rg_release_acceptance_v1.py','news_rg_source_shadow_ingest_v1.py',
 'news_rg_approved_video_publication_v1.py','news_rg_video_watermark_handoff_v1.py',
 'news_rg_nas_video_schedule_v1.py','news_rg_editorial_ai_gate_v1.py')
RELEASE=R/'visual_only_and_service_caption_20261114'
ARCH=RELEASE/'pinned_visual_only.tar.gz'
BACKUP=RELEASE/'pinned_before.json'
RECEIPT=RELEASE/'receipt.json'
LOCKS=(R/'release.lock',O/'news_rg_private_dispatch.lock',
       O/'news_rg_dispatch_schedule.lock')
PY=O/'tools/python-3.15.2/bin/python3.15'
class Stop(ValueError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def safe(p,limit=1100000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or not 1<=st.st_size<=limit or st.st_uid!=0:
  raise Stop('UNSAFE_FILE_'+p.name)
 return p.read_bytes()
def rootdir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 st=p.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
  raise Stop('UNSAFE_DIR_'+p.name)
def replace_once(s,old,new,reason):
 if s.count(old)!=1:raise Stop('PATCH_ANCHOR_DRIFT_'+reason)
 return s.replace(old,new,1)
def patches(old):
 sender=old[str(SENDER)].decode('utf8')
 sender=replace_once(sender,
  "  if item.get('editorial_status') not in ('HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED','HUMAN_FACT_AND_VIDEO_REVIEW_REQUIRED','HUMAN_FACT_AND_TEXT_REVIEW_REQUIRED'):continue",
  """  # User rule: no TEXT-only Telegram moderation cards. Keep source draft
  # untouched for future explicitly generated, clearly labelled AI illustration.
  if item.get('media_type')=='text':continue
  if item.get('editorial_status') not in ('HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED','HUMAN_FACT_AND_VIDEO_REVIEW_REQUIRED'):continue""",
  'sender_eligible')
 sender=replace_once(sender,
  " if item_kind=='text':\n  if item.get('original_video_reference_unavailable') is True:die('VIDEO_TEXT_PROXY_REFUSED')",
  """ if item_kind=='text':
  die('VISUAL_REQUIRED_TEXT_ONLY_PRIVATE_DELIVERY_DISABLED')
  if item.get('original_video_reference_unavailable') is True:die('VIDEO_TEXT_PROXY_REFUSED')""",
  'sender_immediate')
 # Prevent the private caption from misrepresenting AI visuals as originals.
 sender=replace_once(sender,
  " else 'Факти та фото потребують перевірки.\\n\\n')+text)[:1000]",
  """ else ('ІЛЮСТРАЦІЯ ШІ. Це не документальне фото події. Перевірте факти та зображення.\\n\\n'
              if item.get('visual_origin')=='AI_GENERATED_ILLUSTRATION'
              else 'Факти та фото потребують перевірки.\\n\\n'))+text)[:1000]""",
  'ai_media_disclosure')
 minute=old[str(MINUTE)].decode('utf8')
 minute=replace_once(minute,
  "item('caption', FOOTER.encode())",
  "item('caption', b'')",
  'minute_caption')
 minute=replace_once(minute,
  "    assert '<a href=\"https://links.rginfoua.pp.ua/\">' in FOOTER",
  """    assert b'links.rginfoua.pp.ua' not in multipart(-1001755891079)[1]""",
  'minute_selftest')
 alert=old[str(ALERT)].decode('utf8')
 alert=replace_once(alert,"    return body+'\\n\\n'+FOOTER","    return body",
                    'alert_caption')
 output={str(SENDER):sender.encode('utf8'),str(MINUTE):minute.encode('utf8'),
         str(ALERT):alert.encode('utf8')}
 for name,b in output.items():compile(b,name,'exec')
 return output
def inspect():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 rootdir(O);rootdir(R)
 if any(p.is_symlink() for p in (*LOCKS,PIN,RELEASE,ARCH,BACKUP,RECEIPT)):
  raise Stop('RELEASE_SYMLINK')
 if RELEASE.exists():raise Stop('RELEASE_ALREADY_ATTEMPTED')
 before={}
 for p,h in OLD_HASH.items():
  b=safe(Path(p))
  if sha(b)!=h:raise Stop('SOURCE_SHA_DRIFT_'+Path(p).name)
  before[p]=b
 raw=safe(PIN,65000);state=json.loads(raw)
 if state.get('version')!=VERSION or state.get('schema')!='RG_NEWS_STABILITY_RELEASE_V1':
  raise Stop('GUARD_VERSION_CHANGED')
 if state.get('acceptance')!='PASS' or set(state.get('files',{}))!=set(KEY):
  raise Stop('GUARD_MEMBER_SET_CHANGED')
 files={}
 for n in KEY:
  b=safe(O/n)
  if sha(b)!=state['files'][n]:raise Stop('GUARD_FILE_DRIFT_'+n)
  files[n]=b
 original_archive=Path(state['last_known_good_archive'])
 if not original_archive.is_file() or original_archive.is_symlink():
  raise Stop('EXISTING_ARCHIVE_UNAVAILABLE')
 with tarfile.open(original_archive,'r:gz') as tf:
  if set(tf.getnames())!=set(KEY):raise Stop('OLD_ARCHIVE_CONTENTS')
  for n in KEY:
   m=tf.getmember(n)
   if not m.isfile() or sha(tf.extractfile(m).read())!=sha(files[n]):
    raise Stop('OLD_ARCHIVE_HASH_'+n)
 output=patches(before)
 return raw,state,before,files,output
def atomic(p,b,mode=0o600):
 fd,t=tempfile.mkstemp(prefix='.rg_visual_only_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(t,p)
 finally:
  if os.path.exists(t):os.unlink(t)
def create_arch(dst,rows):
 fd,t=tempfile.mkstemp(prefix='.rg_visual_lkg_',dir=str(dst.parent),suffix='.tar.gz')
 os.close(fd)
 try:
  with tarfile.open(t,'w:gz') as tf:
   for n in KEY:
    b=rows[n]
    m=tarfile.TarInfo(n);m.uid=m.gid=0;m.mode=0o600;m.mtime=int(time.time());m.size=len(b)
    tf.addfile(m,io.BytesIO(b))
  os.chmod(t,0o600)
  with tarfile.open(t,'r:gz') as tf:
   for n in KEY:
    if sha(tf.extractfile(n).read())!=sha(rows[n]):raise Stop('LKG_CANDIDATE_HASH_'+n)
  os.replace(t,dst)
 finally:
  if os.path.exists(t):os.unlink(t)
def lock_all():
 fds=[]
 try:
  for p in LOCKS:
   fd=os.open(str(p),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except Exception:os.close(fd);raise
   fds.append(fd)
  return fds
 except Exception:
  for f in reversed(fds):os.close(f)
  raise Stop('LIVE_GUARD_OR_SENDER_BUSY')
def tests(new):
 # No real Telegram calls: sender selftest is isolated; memorial selftest
 # only verifies immutable asset and local DB (do NOT run - it writes DB).
 # Verify source code, known hard gates and media provenance.
 s=new[str(SENDER)].decode('utf8')
 assert "if item.get('media_type')=='text':continue" in s
 assert "die('VISUAL_REQUIRED_TEXT_ONLY_PRIVATE_DELIVERY_DISABLED')" in s
 assert "visual_origin')=='AI_GENERATED_ILLUSTRATION'" in s
 assert "item('caption', b'')" in new[str(MINUTE)].decode('utf8')
 assert "return body+'\\n\\n'+FOOTER" not in new[str(ALERT)].decode('utf8')
 for p,b in new.items():compile(b,p,'exec')
 return True
def acceptance():
 cp=subprocess.run([str(PY),str(O/'news_rg_release_acceptance_v1.py')],
  capture_output=True,text=True,timeout=100)
 if cp.returncode or 'NEWS_RG_RELEASE_ACCEPTANCE_PASS' not in cp.stdout:
  raise Stop('STABLE_ACCEPTANCE_FAILED')
 cp=subprocess.run([str(PY),str(SENDER),'selftest'],
  capture_output=True,text=True,timeout=20)
 if cp.returncode or 'NEWS_RG_DURABLE_PRIVATE_MULTIPART_SELFTEST_PASS' not in cp.stdout:
  raise Stop('SENDER_SELFTEST_FAILED')
 return True
def apply():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 fds=lock_all()
 try:
  oldmeta,meta,old,full,new=inspect()
  tests(new)
  rootdir(RELEASE,create=True)
  atomic(BACKUP,oldmeta)
  for name,b in old.items():
   atomic(RELEASE/('before_'+Path(name).name),b)
  if safe(BACKUP,65000)!=oldmeta:raise Stop('BACKUP_PIN_INVALID')
  if any(sha(safe(RELEASE/('before_'+Path(name).name)))!=OLD_HASH[name] for name in old):
   raise Stop('BACKUP_MODULE_INVALID')
  modified=[]
  try:
   for name,b in new.items():
    p=Path(name);mode=stat.S_IMODE(p.stat().st_mode)
    modified.append((p,mode))
    atomic(p,b,mode)
    if sha(safe(p))!=sha(b):raise Stop('POST_PATCH_HASH_'+p.name)
   acceptance()
   full[SENDER.name]=new[str(SENDER)]
   create_arch(ARCH,full)
   pinned=dict(meta)
   pinned['version']=NEXT
   pinned['installed_at']=int(time.time())
   pinned['prior_archive']=meta['last_known_good_archive']
   pinned['last_known_good_archive']=str(ARCH)
   pinned['files']=dict(meta['files'])
   pinned['files'][SENDER.name]=sha(new[str(SENDER)])
   pinned['acceptance']='PASS'
   pinned['visual_only_moderation_release']='2026-11-14'
   atomic(PIN,(json.dumps(pinned,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
   if json.loads(safe(PIN,65000)).get('version')!=NEXT:
    raise Stop('PINNED_POSTINSTALL_VERSION')
   acceptance()
   rec={'status':'APPLIED_QA_PASS','release':'RG_NEWS2_VISUAL_ONLY_MODERATION_AND_SPECIAL_NAS_CAPTIONS_20261114',
        'new_version':NEXT,'previous_version':VERSION,'modules_pinned':len(KEY),
        'modified_sha256':{Path(k).name:sha(v) for k,v in new.items()},
        'backup_verified':True,'new_archive_sha256':sha(safe(ARCH,10000000)),
        'manual_text_drafts_preserved':True,
        'no_generated_image_claim_without_provider':True,
        'telegram_api_calls':0,'publications':0}
   atomic(RECEIPT,(json.dumps(rec,sort_keys=True)+'\n').encode('utf8'))
   return rec
  except Exception:
   for p,mode in reversed(modified):
    atomic(p,old[str(p)],mode)
   atomic(PIN,oldmeta)
   if safe(PIN,65000)!=oldmeta or any(sha(safe(Path(p)))!=OLD_HASH[p] for p in old):
    raise Stop('ROLLBACK_VERIFICATION_FAILED')
   raise
 finally:
  for fd in reversed(fds):os.close(fd)
def selftest():
 assert len(KEY)==18 and len(OLD_HASH)==3
 assert all(len(v)==64 for v in OLD_HASH.values())
 print('RG_NEWS2_VISUAL_AND_CAPTION_RELEASE_SELFTEST_PASS')
if __name__=='__main__':
 try:
  a=sys.argv[1:]
  if a==['selftest']:selftest()
  elif a==['preflight']:
   oldmeta,state,old,files,new=inspect()
   tests(new)
   print(json.dumps({'status':'PREFLIGHT_PASS','old_pin':state['version'],
       'modules_verified':len(files),'modified_sha256':{Path(k).name:sha(v) for k,v in new.items()},
       'telegram_calls':0,'publications':0},sort_keys=True))
  elif a==['apply']:print(json.dumps(apply(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:170],
      'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
