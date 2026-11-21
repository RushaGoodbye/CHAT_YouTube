#!/usr/bin/env python3
"""RG NEWS2: remove 20MB native-video preflight veto, preserve Telegram file_id.

Uses protected release's lock, full snapshots, offline acceptance and rollback.
Does not download video, send Telegram API calls, start a poller or publish.
"""
import ast,datetime as dt,fcntl,hashlib,importlib.util,io,json,os,pathlib,sys,tarfile,tempfile
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=O/'news_rg_stability_releases_v1';G=O/'news_rg_guarded_release_v1.py'
MAN=R/'pinned_release_v1.json'; I='news_rg_manual_link_intake_v1.py'
S='news_rg_durable_private_sender_v1.py'; P='news_rg_poll_moderation_v1.py'
PSHA='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
OLD=""" if meta['file_size']>20_000_000:
  return {'status':'NATIVE_VIDEO_OVER_20MB_BOT_DOWNLOAD_LIMIT','publications':0}
"""
NEW=""" # Large Telegram-native MP4 is held by its verified file_id. Bot API
 # getFile's hosted 20 MB download limit is NOT a sendVideo(file_id) limit.
 # Stage the original video for private review, without downloading its bytes.
"""
TAG='+native-video-over20-fileid-review-20261121'
def digest(b):return hashlib.sha256(b).hexdigest()
def need(v,s):
 if not v:raise RuntimeError(s)
def say(**v):print(json.dumps(v,ensure_ascii=False,indent=2),flush=True)
def atomic(p,data):
 fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.rg_largevideo_')
 try:
  os.fchmod(fd,p.stat().st_mode&0o777)
  with os.fdopen(fd,'wb') as f:
   f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run():
 need(os.geteuid()==0,'ROOT_REQUIRED')
 for p in (G,MAN,O/I,O/S,O/P):
  need(p.is_file() and not p.is_symlink(),'MISSING_FILE_'+p.name)
 spec=importlib.util.spec_from_file_location('rg_news_guard',str(G))
 guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
 need(pathlib.Path(guard.STATE)==MAN and {I,S,P}.issubset(set(guard.KEY)),'GUARDED_RELEASE_CONTRACT_CHANGED')
 lock=guard.acquire()
 changed=False;originals=None;oldmeta=None;backup=None
 try:
  meta=json.loads(MAN.read_text('utf8'));files=meta.get('files')
  need(meta.get('schema')=='RG_NEWS_STABILITY_RELEASE_V1' and isinstance(files,dict),'MANIFEST_UNEXPECTED')
  need(set(files)==set(guard.KEY) and len(files)==23,'PROTECTED_FILE_SET_CHANGED')
  need(isinstance(meta.get('last_known_good_archive'),str) and meta['last_known_good_archive'],'ARCHIVE_FIELD_MISSING')
  need(isinstance(meta.get('version'),str) and TAG not in meta['version'],'ALREADY_VERSIONED')
  originals={n:(O/n).read_bytes() for n in guard.KEY}
  need(all(digest(originals[n])==files[n] for n in guard.KEY),'PROTECTED_DRIFT')
  need(digest(originals[P])==PSHA,'PUBLIC_POLL_GATE_CHANGED')
  src=originals[I].decode('utf8');sender=originals[S].decode('utf8')
  need(src.count(OLD)==1,'LARGE_VIDEO_VETO_ANCHOR_CHANGED')
  need('def stage_native_video_file(msg):' in src and
       'original_video_file_id' in src and
       'original_video_file_size' in src and
       'MANUAL_LINK_ALREADY_QUEUED' in src and
       "dispatch_once_async()" in src,'NATIVE_VIDEO_STAGING_GUARDS_MISSING')
  need('native_video_id' in sender and
       "'video':native_video_id" in sender and
       'ORIGINAL_TELEGRAM_VIDEO_FILE_ID' in sender and
       'VIDEO_WATERMARK_REQUIRED' in sender,'PRIVATE_VIDEO_FILEID_ROUTE_NOT_VERIFIED')
  updated=src.replace(OLD,NEW,1)
  ast.parse(updated,filename=I)
  need(OLD not in updated and updated.count(NEW)==1,'PATCH_VERIFY_FAILED')
  # Keep 2 GB metadata guard and original-video-only provenance protection.
  for marker in ('2_000_000_000','VIDEO_SOURCE_NOT_VERIFIED_NO_PHOTO_SUBSTITUTION',
                 'MANUAL_LINK_ALREADY_STAGED_NO_RETRY','MANUAL_LINK_PREVIOUSLY_PUBLISHED_NO_RETRY'):
   need(marker in updated,'INTAKE_GUARD_MISSING_'+marker)
  stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  backup=R/('native_video_pre20_'+stamp+'.tar.gz')
  cand=R/('native_video_pinned_'+stamp+'.tar.gz')
  need(not backup.exists() and not cand.exists(),'BACKUP_COLLISION')
  with tarfile.open(backup,'x:gz') as z:
   for n in guard.KEY:z.add(O/n,arcname=n,recursive=False)
  os.chmod(backup,0o600)
  newbytes=updated.encode('utf8')
  with tarfile.open(cand,'x:gz') as z:
   for n in guard.KEY:
    b=newbytes if n==I else originals[n]
    info=tarfile.TarInfo(n);info.size=len(b);info.mode=(O/n).stat().st_mode&0o777
    z.addfile(info,io.BytesIO(b))
  os.chmod(cand,0o600)
  oldmeta=MAN.read_bytes()
  changed=True
  atomic(O/I,newbytes)
  need(digest((O/P).read_bytes())==PSHA,'PUBLICATION_GATE_DRIFT')
  guard.acceptance()
  new=dict(meta)
  newfiles=dict(files);newfiles[I]=digest(newbytes)
  new['files']=newfiles;new['version']=meta['version']+TAG
  new['prior_archive']=meta['last_known_good_archive']
  oldpath=meta['last_known_good_archive']
  new['last_known_good_archive']=str(cand) if pathlib.Path(oldpath).is_absolute() else cand.name
  guard.atomic_json(MAN,new)
  need(all(digest((O/n).read_bytes())==newfiles[n] for n in guard.KEY),'REPIN_VERIFY_FAILED')
  say(status='NATIVE_VIDEO_OVER20_ACCEPTED_BY_FILEID_PINNED_PASS',
      backup=backup.name,release=new['version'],protected_modules=23,
      behavior='STAGE_ORIGINAL_FILE_ID_FOR_PRIVATE_MODERATION',
      supported_video_bytes='1_TO_2000000000',
      large_video_bytes_downloaded=0, private_video_delivery='NOT_LIVE_TESTED',
      local_video_copy_on_NAS='NOT_IMPLEMENTED',
      original_video_no_photo_substitution=True,private_review_required=True,
      duplicate_guards='PRESERVED',public_publication='OFF',
      telegram_calls=0,new_pollers=0,publications=0)
 except Exception:
  if changed and originals:
   try:
    atomic(O/I,originals[I])
    if oldmeta:guard.atomic_json(MAN,json.loads(oldmeta))
    say(status='ROLLBACK_RESTORED',backup=backup.name if backup else None,publications=0)
   except Exception as e:
    say(status='ROLLBACK_REQUIRES_MANUAL_ATTENTION',error_type=type(e).__name__,backup=backup.name if backup else None)
  raise
 finally:
  fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)
if __name__=='__main__':
 try:run()
 except Exception as e:
  say(status='SAFE_STOP',reason=str(e)[:240],telegram_calls=0,publications=0,new_pollers=0)
  sys.exit(2)
