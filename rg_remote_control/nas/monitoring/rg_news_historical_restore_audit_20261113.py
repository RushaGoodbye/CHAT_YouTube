#!/usr/bin/env python3
"""RG NEWS2 historical backup drill, read-only. No production writes or Telegram calls."""
from pathlib import Path
from datetime import datetime,timezone
import os,json,time,sqlite3,tempfile,tarfile,zipfile,gzip,shutil,hashlib
B=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
ROOT=B/'autonomous_backups_v1'
OUT={'audit_at_utc':datetime.now(timezone.utc).isoformat(),'backup_root_exists':ROOT.is_dir(),'historical_db_restore':'NOT_VERIFIED','telegram_api_calls':0,'production_file_writes':0}
MAX=150*1024*1024
def safety(p):
 return p.is_file() and not p.is_symlink() and p.stat().st_size<=MAX
def candidates():
 files=[]
 for p in ROOT.rglob('*'):
  if len(files)>=400:break
  try:
   if safety(p) and (p.name.lower().endswith(('.sqlite3','.sqlite','.db','.sqlite3.gz','.db.gz','.zip','.tar.gz','.tgz'))):files.append(p)
  except OSError:pass
 return sorted(files,key=lambda p:p.stat().st_mtime,reverse=True)
def add(v):
 d={'kind':v.suffix.lower(),'age_hours':round((time.time()-v.stat().st_mtime)/3600,2),'size_bytes':v.stat().st_size}
 return d
def check_db(path):
 con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
 try:
  row=con.execute('PRAGMA integrity_check').fetchone()
  integrity=row[0] if row else 'no_result'
  has_candidates=con.execute("SELECT count(*) FROM sqlite_master WHERE name='candidates' AND type='table'").fetchone()[0]>0
  n=con.execute('SELECT count(*) FROM candidates').fetchone()[0] if has_candidates else None
  return integrity,n
 finally:con.close()
def extract_single(p,dst):
 lower=p.name.lower()
 if lower.endswith(('.sqlite3','.sqlite','.db')):
  shutil.copyfile(p,dst);return 'raw_sqlite'
 if lower.endswith(('.sqlite3.gz','.db.gz')):
  with gzip.open(p,'rb') as r,open(dst,'wb') as w:
   remaining=MAX
   while True:
    chunk=r.read(min(1024*1024,remaining+1))
    if not chunk:break
    remaining-=len(chunk)
    if remaining<0:raise ValueError('oversize_unpacked')
    w.write(chunk)
  return 'gzip_sqlite'
 if lower.endswith(('.tar.gz','.tgz')):
  with tarfile.open(p,'r:gz') as tf:
   members=[m for m in tf.getmembers() if m.isfile() and m.name.lower().endswith(('.sqlite3','.sqlite','.db'))]
   if len(members)!=1 or members[0].size>MAX:raise ValueError('archive_db_selection')
   m=members[0]
   if m.issym() or m.islnk():raise ValueError('unsafe_member')
   f=tf.extractfile(m)
   if not f:raise ValueError('empty_member')
   with open(dst,'wb') as w:shutil.copyfileobj(f,w)
  return 'tar_sqlite'
 if lower.endswith('.zip'):
  with zipfile.ZipFile(p) as z:
   items=[x for x in z.infolist() if not x.is_dir() and x.filename.lower().endswith(('.sqlite3','.sqlite','.db'))]
   if len(items)!=1 or items[0].file_size>MAX:raise ValueError('zip_db_selection')
   with z.open(items[0]) as r,open(dst,'wb') as w:shutil.copyfileobj(r,w)
  return 'zip_sqlite'
 raise ValueError('unknown_format')
try:
 found=candidates()
 OUT['historical_candidate_count']=len(found)
 OUT['recent_backup_shapes']=[add(p) for p in found[:12]]
 for p in found[:12]:
  try:
   with tempfile.TemporaryDirectory(prefix='rg_historical_restore_') as temp:
    dst=Path(temp)/'historical.sqlite3'
    typ=extract_single(p,dst)
    if dst.stat().st_size>MAX:raise ValueError('unpacked_too_large')
    integ,n=check_db(dst)
    if integ=='ok' and n is not None:
     OUT['historical_db_restore']='PASS_ISOLATED_HISTORICAL_BACKUP'
     OUT['historical_recovered_rows']=n
     OUT['historical_format']=typ
     OUT['historical_backup_age_hours']=round((time.time()-p.stat().st_mtime)/3600,2)
     break
  except Exception as exc:
   OUT.setdefault('restore_attempt_fail_classes',[]).append(type(exc).__name__)
 if OUT['historical_db_restore']!='PASS_ISOLATED_HISTORICAL_BACKUP':
  OUT['historical_db_restore']='NOT_VERIFIED_BACKUP_FORMAT_OR_CONTENT'
except Exception as exc:OUT['audit_error']=type(exc).__name__
print(json.dumps(OUT,ensure_ascii=False,indent=2,sort_keys=True))
