#!/usr/bin/env python3
"""NEWS2 guarded source-name veto removal, full pinned archive and rollback."""
import ast,datetime as dt,hashlib,importlib.util,io,json,os,pathlib,sys,tarfile,tempfile,fcntl
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator');R=O/'news_rg_stability_releases_v1'
GUARD=O/'news_rg_guarded_release_v1.py';MAN=R/'pinned_release_v1.json'
I='news_rg_manual_link_intake_v1.py';T='news_rg_manual_retry_v1.py'
P='news_rg_poll_moderation_v1.py'
PSHA='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
A=' if source_requires_satire_review(link):\n'
B=' if False and source_requires_satire_review(link):\n'
C=" if m.source_requires_satire_review(url):\n  return {'status':'SATIRE_REVIEW_REQUIRED'}\n"
D=' # Channel name alone cannot block original-source review.\n'
TAG='+satire-source-veto-removed-20261120'
def digest(x):return hashlib.sha256(x).hexdigest()
def require(x,why):
 if not x:raise RuntimeError(why)
def say(**x):print(json.dumps(x,ensure_ascii=False,indent=2),flush=True)
def atomic(p,b):
 fd,tmp=tempfile.mkstemp(prefix='.source_review_',dir=p.parent)
 try:
  os.fchmod(fd,p.stat().st_mode&0o777)
  with os.fdopen(fd,'wb') as f:
   f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run():
 require(os.geteuid()==0,'ROOT_REQUIRED')
 for p in (GUARD,MAN,O/I,O/T,O/P):
  require(p.is_file() and not p.is_symlink(),'LIVE_FILE_MISSING_'+p.name)
 spec=importlib.util.spec_from_file_location('rg_guarded',str(GUARD))
 g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
 require(set((I,T,P)).issubset(set(g.KEY)) and pathlib.Path(g.STATE)==MAN,'GUARD_CONTRACT_CHANGED')
 lock=g.acquire();originals=None;oldmeta=None;changed=False;backup=None
 try:
  m=json.loads(MAN.read_text('utf8'));f=m.get('files')
  require(m.get('schema')=='RG_NEWS_STABILITY_RELEASE_V1' and isinstance(f,dict),'MANIFEST_SCHEMA_UNEXPECTED')
  require(set(f)==set(g.KEY) and len(f)==23,'PINNED_FILES_CHANGED')
  require(isinstance(m.get('version'),str) and isinstance(m.get('last_known_good_archive'),str) and m['last_known_good_archive'],'PIN_ARCHIVE_FORMAT_UNKNOWN')
  originals={n:(O/n).read_bytes() for n in g.KEY}
  require(all(digest(originals[n])==f[n] for n in g.KEY),'PINNED_DRIFT_STOP')
  require(digest(originals[P])==PSHA,'PUBLIC_GATE_CHANGED')
  oldmeta=MAN.read_bytes()
  stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  backup=R/('satire_before_'+stamp+'.tar.gz')
  cand=R/('satire_pinned_'+stamp+'.tar.gz')
  require(not backup.exists() and not cand.exists(),'BACKUP_COLLISION')
  with tarfile.open(backup,'x:gz') as z:
   for n in g.KEY:z.add(O/n,arcname=n,recursive=False)
  os.chmod(backup,0o600)
  a=originals[I].decode('utf8');b=originals[T].decode('utf8')
  if B in a and C not in b:
   say(status='ALREADY_PATCHED',backup=backup.name,files_modified=0,publications=0);return
  require(a.count(A)==1 and B not in a,'INTAKE_SOURCE_CHANGED')
  require(b.count(C)==1,'RETRY_SOURCE_CHANGED')
  ia=a.replace(A,B,1);tb=b.replace(C,D,1)
  ast.parse(ia);ast.parse(tb)
  for token in ('MANUAL_LINK_ALREADY_STAGED_NO_RETRY','MANUAL_LINK_PREVIOUSLY_PUBLISHED_NO_RETRY','MANUAL_DURABLE_QUEUE_FAILED','source_to_post(link)'):
   require(token in ia,'INTAKE_GUARD_MISSING')
  require('if already_staged(url):' in tb,'RETRY_DEDUP_MISSING')
  mods={I:ia.encode('utf8'),T:tb.encode('utf8')}
  with tarfile.open(cand,'x:gz') as z:
   for n in g.KEY:
    data=mods.get(n,originals[n]);ti=tarfile.TarInfo(n)
    ti.size=len(data);ti.mode=(O/n).stat().st_mode&0o777
    z.addfile(ti,io.BytesIO(data))
  os.chmod(cand,0o600)
  guard_src=GUARD.read_text('utf8')
  require('last_known_good_archive' in guard_src and 'prior_archive' in guard_src,'RELEASE_CONTRACT_UNKNOWN')
  changed=True
  for n,data in mods.items():atomic(O/n,data)
  require(digest((O/P).read_bytes())==PSHA,'PUBLIC_GATE_DRIFT')
  g.acceptance()
  updated=dict(f)
  for n,data in mods.items():updated[n]=digest(data)
  new=dict(m);new['files']=updated;new['version']=m['version']+TAG
  new['prior_archive']=m['last_known_good_archive']
  oldpath=m['last_known_good_archive']
  new['last_known_good_archive']=str(cand) if pathlib.Path(oldpath).is_absolute() else cand.name
  g.atomic_json(MAN,new)
  require(all(digest((O/n).read_bytes())==updated[n] for n in g.KEY),'POST_INSTALL_HASH_MISMATCH')
  say(status='SATIRE_SOURCE_VETO_REMOVED_PINNED_PASS',backup=backup.name,
      release=new['version'],protected_modules=len(updated),v6='PASS',
      manual_moderation='UNCHANGED',duplicates='GUARDS_PRESERVED',
      front='NOT_TOUCHED',public_poll_reenabled=False,telegram_calls=0,publications=0)
 except Exception:
  if changed and originals is not None:
   try:
    for n in (I,T):atomic(O/n,originals[n])
    if oldmeta is not None:g.atomic_json(MAN,json.loads(oldmeta))
    say(status='ROLLBACK_RESTORED',backup=backup.name if backup else None,publications=0)
   except Exception as e:
    say(status='ROLLBACK_REQUIRES_ATTENTION',error_type=type(e).__name__,
        backup=backup.name if backup else None,publications=0)
  raise
 finally:
  fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)
if __name__=='__main__':
 try:run()
 except Exception as e:
  say(status='SAFE_STOP',reason=str(e)[:240],telegram_calls=0,publications=0)
  sys.exit(2)
