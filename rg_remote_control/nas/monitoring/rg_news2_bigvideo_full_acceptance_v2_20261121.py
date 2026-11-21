#!/usr/bin/env python3
"""NEWS2 2026-11-21: large native Telegram videos, updated acceptance fixture.
Transactional 23-component pinned release; zero Telegram calls, public sends or pollers.
"""
import ast,datetime as dt,fcntl,hashlib,importlib.util,io,json,os,pathlib,sys,tarfile,tempfile
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=O/'news_rg_stability_releases_v1';MAN=R/'pinned_release_v1.json'
G=O/'news_rg_guarded_release_v1.py'
INTAKE='news_rg_manual_link_intake_v1.py';POLL='news_rg_poll_moderation_v1.py'
POLL_SHA='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
TAG='+native-video-over20-full-test-contract-v2-20261121'
OLD=""" if meta['file_size']>20_000_000:
  return {'status':'NATIVE_VIDEO_OVER_20MB_BOT_DOWNLOAD_LIMIT','publications':0}
"""
NEW=""" # Telegram-hosted getFile cannot download large MP4s, but a verified
 # video file_id can be reused to deliver the ORIGINAL video privately.
 # Never invent a CDN URL or replace the video with a thumbnail.
"""
TEST_OLD="assert rejected['status']=='NATIVE_VIDEO_OVER_20MB_BOT_DOWNLOAD_LIMIT',rejected"
TEST_NEW=("assert rejected['status']=='MANUAL_LINK_STAGED' and "
          "rejected.get('media_type')=='video' and rejected.get('draft_id'),rejected")
def sha(b):return hashlib.sha256(b).hexdigest()
def require(c,s):
 if not c:raise RuntimeError(s)
def emit(**x):print(json.dumps(x,ensure_ascii=False,indent=2),flush=True)
def atomic(p,b):
 fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.rg_bigvid_')
 try:
  os.fchmod(fd,p.stat().st_mode & 0o777)
  with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run():
 require(os.geteuid()==0,'SUDO_REQUIRED')
 for p in (G,MAN,O/INTAKE,O/POLL):
  require(p.is_file() and not p.is_symlink(),'MISSING_OR_SYMLINK_'+p.name)
 sp=importlib.util.spec_from_file_location('rg_largevid_guard',str(G))
 guard=importlib.util.module_from_spec(sp);sp.loader.exec_module(guard)
 require(pathlib.Path(guard.STATE)==MAN,'GUARDED_RELEASE_STATE_CHANGED')
 lock=guard.acquire();changed=False;originals=None;oldmeta=None;backup=None
 try:
  m=json.loads(MAN.read_text('utf8'));files=m.get('files')
  require(m.get('schema')=='RG_NEWS_STABILITY_RELEASE_V1' and isinstance(files,dict),'MANIFEST_SCHEMA_CHANGED')
  require(len(files)==23 and set(files)==set(guard.KEY),'GUARDED_RELEASE_COMPONENTS_CHANGED')
  require(TAG not in m.get('version',''),'ALREADY_VERSIONED')
  require(isinstance(m.get('last_known_good_archive'),str) and m['last_known_good_archive'],'ARCHIVE_CONFIG_MISSING')
  originals={n:(O/n).read_bytes() for n in guard.KEY}
  require(all(sha(originals[n])==files[n] for n in guard.KEY),'PINNED_HASH_DRIFT')
  require(sha(originals[POLL])==POLL_SHA,'PUBLIC_POLL_PROTECTION_CHANGED')
  txt=originals[INTAKE].decode('utf8')
  require(txt.count(OLD)==1,'LIVE_20MB_REJECTION_NOT_UNIQUE')
  require('def stage_native_video_file(msg):' in txt and
   'original_video_file_id' in txt and 'original_video_file_size' in txt and
   'NATIVE_VIDEO_FILE_ID_UNVERIFIED' in txt and
   'MANUAL_LINK_ALREADY_QUEUED' in txt and
   "dispatch_once_async()" in txt,'REQUIRED_INTAKE_GUARDS_MISSING')
  require('2_000_000_000' in txt and 'VIDEO_SOURCE_NOT_VERIFIED_NO_PHOTO_SUBSTITUTION' in txt,
     'ORIGINAL_VIDEO_GUARDS_MISSING')
  snd=originals['news_rg_durable_private_sender_v1.py'].decode('utf8')
  require("'video':native_video_id" in snd and
   'ORIGINAL_TELEGRAM_VIDEO_FILE_ID' in snd and
   'VIDEO_WATERMARK_REQUIRED' in snd,'NATIVE_FILEID_SENDER_ROUTE_UNVERIFIED')
  updated={INTAKE:txt.replace(OLD,NEW,1).encode('utf8')}
  fixtures=[]
  for name,srcbytes in originals.items():
   src=updated.get(name,srcbytes).decode('utf8')
   if TEST_OLD in src:
    require(src.count(TEST_OLD)==1,'OUTDATED_ASSERTION_MULTIPLE_'+name)
    src=src.replace(TEST_OLD,TEST_NEW,1)
    updated[name]=src.encode('utf8')
    fixtures.append(name)
  require(fixtures==['news_rg_release_acceptance_v1.py'],
     'EXPECTED_ONE_RELEASE_ACCEPTANCE_ASSERTION_'+repr(fixtures))
  require(OLD not in updated[INTAKE].decode('utf8'),
     'INTAKE_20MB_VETO_NOT_REMOVED')
  # The global acceptance fixture previously asserted rejection AND no new draft,
  # so update the full contract rather than merely changing one status assertion.
  name='news_rg_release_acceptance_v1.py'
  suite=updated[name].decode('utf8')
  old_block="""   assert len(list(st.glob('*.json')))==1
   assert any('20 МБ' in x for x in sent)
   assert all(chr(92)+'n' not in x for x in sent)
 print('PASS native MP4 document / duplicate / >20 MB safe stop / no fake media')"""
  new_block="""   assert rejected['draft_id']!=result['draft_id'],rejected
   large=json.loads((st/(rejected['draft_id']+'.json')).read_text())
   assert large['media_type']=='video' and large['original_video_file_id']==oversized['file_id'],large
   assert large['original_video_file_size']==35000000,large
   assert large['review_media']=='ORIGINAL_TELEGRAM_VIDEO_FILE_ID',large
   assert large['public_publication']=='OFF',large
   assert m.handle(bad,cfg,api)['status']=='MANUAL_LINK_ALREADY_QUEUED'
   assert len(list(st.glob('*.json')))==2
   assert not any('20 МБ' in x for x in sent)
   assert all(chr(92)+'n' not in x for x in sent)
 print('PASS native MP4 document / 35MB staged / duplicate / no fake media')"""
  require(suite.count(old_block)==1,'RELEASE_ACCEPTANCE_FULL_BLOCK_CHANGED')
  suite=suite.replace(old_block,new_block,1)
  require("NATIVE_VIDEO_OVER_20MB_BOT_DOWNLOAD_LIMIT" not in suite,'STALE_REJECTION_IN_ACCEPTANCE')
  updated[name]=suite.encode('utf8')
  # Verify new acceptance scenario actually asserts both original file id and metadata size.
  require("assert large['original_video_file_size']==35000000" in suite,
          'LARGE_FILE_SIZE_ASSERT_MISSING')
  # Acceptance and intake selftests must both validate staged media and dedup.
  for name,b in updated.items():ast.parse(b.decode('utf8'),filename=name)
  stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  backup=R/('bigvideo_before_'+stamp+'.tar.gz')
  cand=R/('bigvideo_pinned_'+stamp+'.tar.gz')
  require(not backup.exists() and not cand.exists(),'BACKUP_COLLISION')
  with tarfile.open(backup,'x:gz') as z:
   for n in guard.KEY:z.add(O/n,arcname=n,recursive=False)
  os.chmod(backup,0o600)
  with tarfile.open(cand,'x:gz') as z:
   for n in guard.KEY:
    b=updated.get(n,originals[n]);inf=tarfile.TarInfo(n);inf.size=len(b)
    inf.mode=(O/n).stat().st_mode&0o777;z.addfile(inf,io.BytesIO(b))
  os.chmod(cand,0o600)
  oldmeta=MAN.read_bytes();changed=True
  for name,b in updated.items():atomic(O/name,b)
  require(sha((O/POLL).read_bytes())==POLL_SHA,'POLL_MODULE_CHANGED_DURING_FIX')
  guard.acceptance()
  newfiles=dict(files)
  for name,b in updated.items():newfiles[name]=sha(b)
  new=dict(m);new['files']=newfiles;new['version']=m['version']+TAG
  new['prior_archive']=m['last_known_good_archive']
  oldpath=m['last_known_good_archive']
  new['last_known_good_archive']=str(cand) if pathlib.Path(oldpath).is_absolute() else cand.name
  guard.atomic_json(MAN,new)
  require(all(sha((O/n).read_bytes())==newfiles[n] for n in guard.KEY),'PINNED_REVALIDATION_FAILED')
  emit(status='LARGE_VIDEO_FILEID_INTAKE_AND_TESTS_PINNED_PASS',
       protected_files=len(newfiles),modified_modules=list(updated),
       updated_fixtures=fixtures,old_veto_removed=True,
       file_id_original_only=True,
       max_metadata_size_bytes=2000000000,
       private_delivery_live_verified=False,
       local_NAS_mp4_copy=False,
       public_poll_gate='UNCHANGED_DISABLED',
       publications=0,telegram_calls=0,new_pollers=0,backup=backup.name)
 except Exception:
  if changed and originals:
   try:
    for n in updated:atomic(O/n,originals[n])
    if oldmeta:guard.atomic_json(MAN,json.loads(oldmeta))
    emit(status='ROLLBACK_RESTORED',backup=backup.name if backup else None,publications=0)
   except Exception as e:emit(status='ROLLBACK_NEEDS_ATTENTION',error_type=type(e).__name__,backup=backup.name if backup else None)
  raise
 finally:
  fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)
if __name__=='__main__':
 try:run()
 except Exception as exc:
  emit(status='SAFE_STOP',reason=str(exc)[:250],publications=0,
   telegram_calls=0,new_pollers=0)
  sys.exit(2)
