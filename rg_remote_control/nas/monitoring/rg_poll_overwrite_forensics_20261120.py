#!/usr/bin/env python3
"""NEWS2 poll override forensics. Read only; no network calls or state edits."""
import os, pathlib, re, json, hashlib, sys, datetime, subprocess
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
TARGET=ROOT/'operator/news_rg_poll_moderation_v1.py'
TERMS=('news_rg_poll_moderation_v1.py','RG_POLL_V6','rg_poll_topnews_policy_v2.py','RG_POLL_SAFETY')
DIRS=[ROOT/'operator',ROOT/'rg_news2_fix_20261119',ROOT, pathlib.Path('/volume1/docker')]
ALLOWED={'.py','.sh','.service','.timer','.conf','.json','.yaml','.yml','.txt','.env'}
IGNORE=('protected_backups','recovery_backups','.git','node_modules','__pycache__','venv','site-packages','archive')
def dt(ts):return datetime.datetime.fromtimestamp(ts,datetime.timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def safe_read(p,maxsize=150000):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>maxsize:return None
  return p.read_text('utf8',errors='replace')
 except Exception:return None
def scan():
 seen=set();results=[];checked=0
 roots=[ROOT/'operator',ROOT/'rg_news2_fix_20261119',ROOT.parent]
 for root in roots:
  if not root.is_dir():continue
  for directory,dirs,files in os.walk(root):
   rel=pathlib.Path(directory)
   if len(rel.parts)-len(root.parts)>3:dirs[:]=[];continue
   dirs[:]=[x for x in dirs if x not in IGNORE and not x.startswith('.')]
   for name in files:
    p=rel/name
    if p in seen or p==TARGET or p.suffix.lower() not in ALLOWED:continue
    seen.add(p);checked+=1
    if checked>3500:break
    src=safe_read(p)
    if src is None:continue
    matched=[{'term':term,'line':i} for i,line in enumerate(src.splitlines(),1) for term in TERMS if term in line]
    if matched:results.append({'path':str(p),'mtime':dt(p.stat().st_mtime),'matches':matched[:16]})
   if checked>3500:break
  if checked>3500:break
 return results,checked
def cron():
 out=[]
 for p in ('/etc/crontab','/usr/syno/etc/schedtask.conf','/etc/cron.d'):
  path=pathlib.Path(p)
  if not path.exists():continue
  if path.is_file():
   s=safe_read(path,250000)
   if s is not None:
    hits=[i for i,l in enumerate(s.splitlines(),1) if ('poll' in l.casefold() or 'RG_TELEGRAM_NEWS_2' in l)]
    out.append({'path':p,'matching_lines':hits[:60]})
  elif path.is_dir():
   for f in list(path.iterdir())[:50]:
    s=safe_read(f)
    if s and ('poll' in s.casefold() or 'RG_TELEGRAM_NEWS_2' in s):
     out.append({'path':str(f),'matching_lines':[i for i,l in enumerate(s.splitlines(),1) if 'poll' in l.casefold() or 'RG_TELEGRAM_NEWS_2' in l][:30]})
 return out
def audit():
 st=TARGET.stat();data=TARGET.read_bytes()
 matches,checked=scan()
 return {'status':'RG_POLL_OVERWRITE_FORENSICS_READONLY',
  'live_sha256':sha(data),'live_modified_at_utc':dt(st.st_mtime),
  'live_size':st.st_size,
  'original_unprotected':sha(data)=='b29d6fa26ec32e77ee51bfd51b1d99b1cb88110def57adb6204de2a14bd4501a',
  'scan_files_checked':checked,'potential_owners':matches[:55],
  'scheduled_entries':cron(),'note':'No files modified. Paths and match line numbers only. No source code or credentials printed.',
  'telegram_calls':0,'publications':0}
if __name__=='__main__':
 try:print(json.dumps(audit(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'FORENSICS_FAILED','reason':type(e).__name__,'telegram_calls':0,'publications':0}))
  sys.exit(2)
