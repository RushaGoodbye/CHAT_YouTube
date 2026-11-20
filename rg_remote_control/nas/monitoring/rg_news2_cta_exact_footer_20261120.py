#!/usr/bin/env python3
"""RG NEWS2 CTA exact-wording patch, safe and fail-closed.

Target footer text:
УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ РАША ГУДБАЙ
Preserves existing HTML/Telegram hyperlink and link destination.
No Telegram calls/publications, no process changes.
Protected pinned-release files are not changed without archive repin.
"""
import ast,datetime as dt,hashlib,json,os,pathlib,re,shutil,sys,tarfile,tempfile
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=ROOT/'operator'
OLD='УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ'
NEW='УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ РАША ГУДБАЙ'
EXPECTED_LINK='https://links.rginfoua.pp.ua/'
BACKUP=OP/'cta_footer_backups'
PINNED=OP/'news_rg_stability_releases_v1/pinned_release_v1.json'
EXCLUDE={'venv','node_modules','__pycache__','.git','tools','news_rg_stability_releases_v1',
'recovery_backups_20261117','cta_footer_backups'}
SUFFIX={'.py','.js','.mjs','.cjs','.sh','.html','.ts'}
def report(**kw):
 print(json.dumps(kw,ensure_ascii=False,indent=2))
def files():
 rows=[]
 for base in (ROOT,OP):
  for p in base.iterdir():
   if p.is_symlink():continue
   if p.is_file() and p.suffix.lower() in SUFFIX:
    rows.append(p)
   elif p.is_dir() and p.name in {'src','publisher','publishing','modules'}:
    for q in p.rglob('*'):
     if q.is_symlink() or not q.is_file() or q.suffix.lower() not in SUFFIX:continue
     if any(x in EXCLUDE for x in q.relative_to(base).parts):continue
     rows.append(q)
 return list(dict.fromkeys(rows))
def pinned_names():
 obj={}
 try:
  if PINNED.is_file() and not PINNED.is_symlink():obj=json.loads(PINNED.read_text('utf8'))
 except Exception:return set(),False
 if not isinstance(obj,dict):return set(),False
 names=set()
 def walk(x):
  if isinstance(x,dict):
   for k,v in x.items():
    if isinstance(k,str) and k.endswith(('.py','.js','.sh','.ts')):names.add(pathlib.Path(k).name)
    walk(v)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(obj)
 return names,bool(names)
def main():
 if not ROOT.is_dir() or not OP.is_dir():return report(status='SAFE_STOP_NO_NEWS2_PROJECT')
 pin,has_pin=pinned_names()
 if not has_pin:return report(status='SAFE_STOP_CANNOT_VERIFY_PINNED_MANIFEST')
 candidates=[];invalid=[]
 pattern=re.compile(re.escape(OLD)+r'(?!\s+РАША\s+ГУДБАЙ)',re.UNICODE)
 for p in files():
  try:
   if p.stat().st_size>1500000:continue
   original=p.read_text('utf8')
  except (OSError,UnicodeError):continue
  matches=len(pattern.findall(original))
  if not matches:continue
  revised=pattern.sub(NEW,original)
  if p.suffix.lower()=='.py':
   try:ast.parse(revised)
   except SyntaxError:
    invalid.append(p.name);continue
  candidates.append((p,original,revised,matches))
 if invalid:return report(status='SAFE_STOP_SYNTAX',files=invalid)
 if not candidates:
  return report(status='NO_SOURCE_WITH_OLD_FOOTER_FOUND',
   exact_required_text=NEW,link_destination=EXPECTED_LINK,
   publications=0,telegram_calls=0)
 protected=[p.name for p,_,_,_ in candidates if p.name in pin]
 if protected:
  return report(status='PINNED_RELEASE_REPIN_REQUIRED_NO_CHANGES',
    protected_sources=protected,
    other_matching_sources=[p.name for p,_,_,_ in candidates if p.name not in pin],
    exact_required_text=NEW,telegram_calls=0,publications=0)
 if BACKUP.is_symlink():return report(status='SAFE_STOP_BACKUP_SYMLINK')
 BACKUP.mkdir(mode=0o700,parents=True,exist_ok=True)
 stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 save=BACKUP/f'footer_before_{stamp}.tar.gz'
 if save.exists() or save.is_symlink():return report(status='SAFE_STOP_BACKUP_COLLISION')
 with tarfile.open(save,'x:gz') as z:
  for p,_,_,_ in candidates:z.add(p,arcname=p.relative_to(ROOT),recursive=False)
 os.chmod(save,0o600)
 updates=[];temp=[]
 try:
  for p,_,revised,_ in candidates:
   fd,tmp=tempfile.mkstemp(prefix='.rgcta_',dir=p.parent)
   with os.fdopen(fd,'w',encoding='utf8') as f:
    os.fchmod(f.fileno(),p.stat().st_mode&0o777)
    f.write(revised);f.flush();os.fsync(f.fileno())
   temp.append(pathlib.Path(tmp))
   os.replace(tmp,p)
   updates.append(p)
  for p,_,revised,_ in candidates:
   if p.read_text('utf8')!=revised:raise RuntimeError('VERIFICATION_FAILED')
 except Exception as e:
  with tarfile.open(save,'r:gz') as z:
   for p in updates:
    f=z.extractfile(str(p.relative_to(ROOT)))
    if f is not None:p.write_bytes(f.read())
  return report(status='ROLLED_BACK',error=type(e).__name__,backup=save.name)
 finally:
  for p in temp:
   if p.exists():p.unlink()
 return report(status='CTA_SOURCE_PATCHED',
   patched_sources=[{'file':str(p.relative_to(ROOT)),'occurrences':cnt} for p,_,_,cnt in candidates],
   exact_required_text=NEW,
   retained_existing_hyperlink=True,
   link_destination=EXPECTED_LINK,
   backup=save.name,
   public_posts_edited=0,telegram_calls=0,publications=0,
   note='New source text still requires validation in the live publisher path')
if __name__=='__main__':
 try:main()
 except Exception as e:
  report(status='CTA_SAFE_STOP',error_type=type(e).__name__,telegram_calls=0,publications=0)
  sys.exit(2)
