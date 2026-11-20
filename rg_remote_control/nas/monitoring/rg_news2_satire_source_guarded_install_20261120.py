#!/usr/bin/env python3
"""NEWS2 guarded satire-source veto hotfix via installed transactional installer.
No Telegram API or new poller. Does NOT touch 'front' alert or public gates.
"""
import ast,datetime,hashlib,json,os,pathlib,subprocess,sys,tarfile
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=R/'operator'
I=O/'news_rg_manual_link_intake_v1.py';T=O/'news_rg_manual_retries_v1.py'
J=R/'rg_news2_satire_audit_20261119.py'
M=O/'news_rg_stability_releases_v1/pinned_release_v1.json'
P=O/'news_rg_poll_moderation_v1.py';G=O/'news_rg_guarded_release_v1.py'
SHA='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
OLD=' if source_requires_satire_review(link):\n'
NEW=' if False and source_requires_satire_review(link):\n'
RETRY_OLD=" if m.source_requires_satire_review(url):\n  return {'status':'SATIRE_REVIEW_REQUIRED'}\n"
def tell(**x):print(json.dumps(x,ensure_ascii=False,indent=2))
def ok(p):return p.is_file() and not p.is_symlink()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def integrity():
 if not all(ok(x) for x in (I,T,J,M,P,G)):raise RuntimeError('REQUIRED_LIVE_FILE_MISSING')
 m=json.loads(M.read_text('utf8')); fs=m.get('files')
 if not isinstance(fs,dict) or fs.get(P.name)!=SHA or sha(P)!=SHA or I.name not in fs or T.name not in fs:
  raise RuntimeError('V6_OR_PINNED_MANIFEST_UNEXPECTED')
 return fs
def main():
 fs=integrity()
 i=I.read_text('utf8');t=T.read_text('utf8');src=J.read_text('utf8')
 for name,body in ((I.name,i),(T.name,t),(J.name,src)):
  ast.parse(body,filename=name)
 if NEW in i and RETRY_OLD not in t:
  tell(status='ALREADY_PATCHED',v6='PASS',publications=0,files_modified=0);return
 if i.count(OLD)!=1 or RETRY_OLD not in t:raise RuntimeError('LIVE_SATIRE_ANCHORS_UNEXPECTED')
 # Run ONLY the pre-existing operator-authored release installer with exact signature.
 required=('satire-content-review-no-source-veto-20261119','SATIRE_INTAKE_ANCHOR_CHANGED',
           'if False and source_requires_satire_review(link)','safe_archive',
           'compile(','backup','replacement(')
 if any(x not in src for x in required):raise RuntimeError('EXISTING_INSTALLER_UNVERIFIED')
 if 'https://api.telegram.org' in src:raise RuntimeError('INSTALLER_NETWORK_REQUIRES_REVIEW')
 folder=O/'news_rg_stability_releases_v1/manual_intake_repair_backups'
 if folder.is_symlink():raise RuntimeError('BACKUP_SYMLINK')
 folder.mkdir(parents=True,exist_ok=True,mode=0o700)
 backup=folder/('satire_release_pre_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.tar.gz')
 if backup.exists():raise RuntimeError('BACKUP_NAME_COLLISION')
 with tarfile.open(backup,'x:gz') as z:
  for name in fs:
   p=O/name
   if ok(p):z.add(p,arcname=str(p.relative_to(R)),recursive=False)
  for p in (M,J,G):
   if ok(p):z.add(p,arcname=str(p.relative_to(R)),recursive=False)
 os.chmod(backup,0o600)
 py=O/'tools/python-3.15.2/bin/python3.15'
 if not ok(py):raise RuntimeError('PYTHON_RUNTIME_MISSING')
 try:
  proc=subprocess.run([str(py),str(J)],cwd=R,capture_output=True,text=True,timeout=180)
 except subprocess.TimeoutExpired:
  tell(status='INSTALLER_TIMEOUT_CHECK_MANUALLY',backup=backup.name,publications=0);return
 post=I.read_text('utf8');retry=T.read_text('utf8')
 integrity()
 if proc.returncode or NEW not in post or RETRY_OLD in retry:
  tell(status='INSTALLER_NOT_ACCEPTED_SAFE_STOP',exit_code=proc.returncode,
    stdout_tail=proc.stdout[-600:],stderr_tail=proc.stderr[-400:],
    backup=backup.name,publications=0);return
 # Check that guarded release does not restore an old version.
 try:
  check=subprocess.run([str(py),str(G),'force-check'],cwd=R,
   capture_output=True,text=True,timeout=75)
 except subprocess.TimeoutExpired:
  tell(status='GUARD_CHECK_TIMEOUT',backup=backup.name,publications=0);return
 ast.parse(I.read_text('utf8'));ast.parse(T.read_text('utf8'))
 integrity()
 if check.returncode or NEW not in I.read_text('utf8') or RETRY_OLD in T.read_text('utf8'):
  tell(status='PINNED_RELEASE_POSTCHECK_FAILED',guard_exit=check.returncode,
       backup=backup.name,publications=0);return
 tell(status='SATIRE_SOURCE_VETO_REMOVED_PINNED_PASS',backup=backup.name,
      v6='PASS',manual_review_dedup_unchanged=True,
      public_poll_reenabled=False,front='NOT_CHANGED_SEPARATE_CHECK',
      public_posts=0,telegram_calls=0,new_pollers=0)
if __name__=='__main__':
 try:main()
 except Exception as e:
  tell(status='SATIRE_INSTALL_SAFE_STOP',reason=str(e)[:140] if isinstance(e,RuntimeError) else type(e).__name__,
       public_posts=0,telegram_calls=0);sys.exit(2)
