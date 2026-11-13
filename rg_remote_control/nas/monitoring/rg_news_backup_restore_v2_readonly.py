#!/usr/bin/env python3
"""NEWS2 safe multi-database archive restoration drill; no production writes or APIs.

Find *news.sqlite3* by exact basename inside validated archives, extract only it
to a bounded isolated temp file, and run read-only SQLite integrity check.
"""
import argparse, gzip, json, os, shutil, sqlite3, tarfile, tempfile, time, zipfile
from pathlib import Path

BASE=Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
BACKUPS=BASE/"autonomous_backups_v1"
MAX_ARCHIVE=160*1024*1024
MAX_UNPACKED=160*1024*1024
MAX_CANDIDATES=100
class Unsafe(ValueError): pass

def candidates():
    if not BACKUPS.is_dir() or BACKUPS.is_symlink(): raise Unsafe("BACKUP_ROOT_MISSING")
    files=[]
    for p in BACKUPS.rglob("*"):
        if len(files)>=MAX_CANDIDATES:break
        try:
            if p.is_symlink() or not p.is_file():continue
            size=p.stat().st_size
            if not 0<size<=MAX_ARCHIVE:continue
            if p.name.lower().endswith((".tar.gz",".tgz",".zip",".sqlite3.gz",".db.gz",".sqlite3",".db")):
                files.append(p)
        except OSError:continue
    return sorted(files,key=lambda p:p.stat().st_mtime,reverse=True)

def choose_archive_member(members):
    # Match the NEWS2 main database, never any other DB in the bundle.
    safe=[]
    for name,size,kind in members:
        parts=Path(name).parts
        if name.startswith("/") or ".." in parts or "\\" in name:continue
        if Path(name).name.lower()=="news.sqlite3" and 0<size<=MAX_UNPACKED and kind=="file":
            safe.append(name)
    if len(safe)!=1:raise Unsafe("NEWS_DB_NOT_UNIQUE_OR_MISSING")
    return safe[0]

def stream_bounded(source,dest):
    count=0
    with open(dest,"xb") as out:
        while True:
            chunk=source.read(1024*1024)
            if not chunk:break
            count+=len(chunk)
            if count>MAX_UNPACKED:raise Unsafe("UNPACK_TOO_LARGE")
            out.write(chunk)
    return count

def extract(path,where):
    dst=where/"news.sqlite3"
    name=path.name.lower()
    if name.endswith((".tar.gz",".tgz")):
        with tarfile.open(path,mode="r:gz") as tar:
            members=[m for m in tar.getmembers() if m.isfile() and not m.issym() and not m.islnk()]
            choice=choose_archive_member([(m.name,m.size,"file") for m in members])
            m=next(m for m in members if m.name==choice)
            src=tar.extractfile(m)
            if src is None:raise Unsafe("MEMBER_UNREADABLE")
            with src:stream_bounded(src,dst)
        return "tar_news_db"
    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            members=[m for m in z.infolist() if not m.is_dir()]
            # symlink entries are rejected by UNIX mode bits
            entries=[(m.filename,m.file_size,"file" if ((m.external_attr>>16)&0o170000)!=0o120000 else "symlink") for m in members]
            choice=choose_archive_member(entries)
            with z.open(choice) as src:stream_bounded(src,dst)
        return "zip_news_db"
    if name.endswith((".sqlite3.gz",".db.gz")):
        if not name.startswith("news.sqlite3"):
            raise Unsafe("NOT_NEWS_DB_GZIP")
        with gzip.open(path,"rb") as src:stream_bounded(src,dst)
        return "gzip_news_db"
    if name=="news.sqlite3":
        with path.open("rb") as src:stream_bounded(src,dst)
        return "raw_news_db"
    raise Unsafe("FORMAT_UNSUPPORTED")

def verify(db):
    uri="file:"+str(db)+"?mode=ro"
    cn=sqlite3.connect(uri,uri=True,timeout=8)
    try:
        cn.execute("PRAGMA query_only=ON")
        result=cn.execute("PRAGMA integrity_check").fetchone()
        n=cn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='candidates'").fetchone()[0]
        if not result or result[0]!="ok" or n!=1:raise Unsafe("SQLITE_INTEGRITY_OR_SCHEMA_FAIL")
        return cn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    finally:cn.close()

def audit():
    fs=candidates()
    out={"schema":"RG_NEWS_BACKUP_RESTORE_V2","read_only":True,
      "candidate_archives":len(fs),"restore_status":"NOT_VERIFIED",
      "attempts":[],"telegram_api_calls":0,"publications":0,
      "production_writes":0,"public_runner_shutdown_allowed":False}
    for p in fs[:19]:
        a={"archive_age_hours":round((time.time()-p.stat().st_mtime)/3600,2),
           "archive_bytes":p.stat().st_size}
        try:
            with tempfile.TemporaryDirectory(prefix="rg_news_restore_v2_") as d:
                mode=extract(p,Path(d))
                count=verify(Path(d)/"news.sqlite3")
                a["result"]="PASS"
                out.update(restore_status="PASS_ISOLATED_NEWS_SQLITE",
                    archive_age_hours=a["archive_age_hours"],archive_format=mode,
                    restored_candidate_rows=count)
                out["attempts"].append(a)
                break
        except (Unsafe,ValueError,OSError,sqlite3.Error,tarfile.TarError,zipfile.BadZipFile,EOFError) as e:
            a["result"]="NOT_VERIFIED";a["reason"]=str(e)[:65] if isinstance(e,Unsafe) else type(e).__name__
        out["attempts"].append(a)
    return out

def selftest():
    assert choose_archive_member([("a/news.sqlite3",123,"file"),("b/other.sqlite3",55,"file")])=="a/news.sqlite3"
    for x in ([("../news.sqlite3",12,"file")],[("a/news.sqlite3",12,"file"),("b/news.sqlite3",15,"file")],[]):
        try:choose_archive_member(x)
        except Unsafe:pass
        else:raise AssertionError("BAD_MEMBER_ACCEPTED")
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"news.sqlite3"
        db=sqlite3.connect(str(p));db.execute("CREATE TABLE candidates (id INTEGER)");db.execute("INSERT INTO candidates VALUES (1)");db.commit();db.close()
        assert verify(p)==1
        z=Path(td)/"sample.tar.gz"
        with tarfile.open(z,"w:gz") as tf:
            tf.add(p,arcname="archive/db/news.sqlite3")
            tf.add(p,arcname="archive/other.sqlite3")
        with tempfile.TemporaryDirectory() as t:
            assert extract(z,Path(t))=="tar_news_db"
            assert verify(Path(t)/"news.sqlite3")==1
    print("RG_NEWS_BACKUP_RESTORE_V2_OFFLINE_SELFTEST_PASS")
    print("MULTIDB_ARCHIVE_SELECTION_SAFE_PASS")

if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("action",choices=["selftest","inspect"]);v=a.parse_args()
    if v.action=="selftest":selftest()
    else:print(json.dumps(audit(),ensure_ascii=False,sort_keys=True,indent=2))
