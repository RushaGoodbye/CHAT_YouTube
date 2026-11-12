#!/usr/bin/env python3
"""Single-pass, root-only, metadata-only NAS diagnostic refresh for DSM scheduler.

DSM Task Scheduler should invoke this via /usr/bin/python3 each 15 minutes,
under root. No network access, no Telegram calls, no runner state changes.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import time

ROOT = Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
OUT = Path("/volume1/docker/RG_TELEGRAM_NEWS_EXPORT")
FILE = "rg_news_health_public.json"
LABELS = {
    "operator": "operator",
    "review_staging": "operator/news_rg_private_review_staging",
    "private_receipts": "operator/news_rg_private_multipart_receipts_v1",
    "editorial_decisions": "operator/news_rg_editorial_decisions_v1",
    "watermark_handoff": "operator/news_rg_video_watermark_handoff_v1",
}

class SafeStop(ValueError):
    pass

def directory(path):
    try:
        info=path.lstat()
    except OSError as e:
        raise SafeStop("DIRECTORY_UNAVAILABLE") from e
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SafeStop("UNSAFE_DIRECTORY")
    return info

def scan(source):
    directory(source)
    result={}
    for label,relative in LABELS.items():
        path=source/relative
        try:
            entry=path.lstat()
        except FileNotFoundError:
            result[label]={"exists":False}
            continue
        except OSError:
            result[label]={"exists":False,"stat_error":True}
            continue
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
            raise SafeStop("UNSAFE_SOURCE_ENTRY")
        result[label]={"exists":True,"directory":True}
    return result

def build(source,now=None):
    stamp=int(time.time()) if now is None else now
    if type(stamp) is not int or stamp<=0:
        raise SafeStop("INVALID_TIMESTAMP")
    return {
        "schema":"RG_NEWS_NAS_SANITIZED_EXPORT_V1",
        "generated_at_unix":stamp,
        "contains_secrets":False,
        "private_messages_read":0,
        "telegram_api_calls":0,
        "publications":0,
        "source":"LOCAL_NAS_METADATA_ONLY",
        "locations":scan(source),
    }

def tick(source=ROOT,out=OUT):
    info=directory(out)
    if info.st_mode & 0o022:
        raise SafeStop("OPEN_EXPORT_DIRECTORY")
    if os.geteuid()==0 and info.st_uid!=0:
        raise SafeStop("EXPORT_DIR_NOT_ROOT_OWNED")
    target=out/FILE
    if target.is_symlink():
        raise SafeStop("SYMLINK_TARGET")
    if target.exists():
        target_info=target.lstat()
        if not stat.S_ISREG(target_info.st_mode) or target_info.st_mode & 0o022:
            raise SafeStop("UNSAFE_TARGET")
    data=build(source)
    temp=None
    try:
        fd,temp=tempfile.mkstemp(prefix=".rg-news-health-",dir=str(out))
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            os.fchmod(stream.fileno(),0o644)
            json.dump(data,stream,sort_keys=True,separators=(",",":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,target)
        temp=None
        # Verify produced data, never access operator file contents.
        stored=json.loads(target.read_text(encoding="utf-8"))
        if stored!=data:raise SafeStop("VERIFY_MISMATCH")
        return {"status":"FRESH_METADATA_ONLY",
                "bot_health_proven":False,
                "telegram_api_calls":0,
                "publications":0}
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)

def selftest():
    with tempfile.TemporaryDirectory() as d:
        base=Path(d)
        source=base/"source";source.mkdir()
        (source/"operator").mkdir(mode=0o700)
        out=base/"out";out.mkdir(mode=0o755)
        result=tick(source,out)
        assert result["status"]=="FRESH_METADATA_ONLY"
        target=out/FILE
        doc=json.loads(target.read_text())
        assert doc["locations"]["operator"]["exists"] is True
        assert doc["private_messages_read"]==0
        assert stat.S_IMODE(target.stat().st_mode)==0o644
        assert scan(source)["review_staging"]=={"exists":False}
        bad=source/"operator"/"news_rg_private_multipart_receipts_v1"
        bad.symlink_to(source/"operator")
        try:tick(source,out)
        except SafeStop as e:assert str(e)=="UNSAFE_SOURCE_ENTRY"
        else:raise AssertionError("SYMLINK_NOT_REJECTED")
        bad.unlink()
        target.unlink()
        target.symlink_to("/etc/passwd")
        try:tick(source,out)
        except SafeStop as e:assert str(e)=="SYMLINK_TARGET"
        else:raise AssertionError("TARGET_SYMLINK_NOT_REJECTED")
    print("SCHEDULED_EXPORT_SELFTEST_PASS")
    print("NO_SECRET_READ_NO_TELEGRAM_CALLS_PASS")
    print("ATOMIC_EXPORT_SYMLINK_PROTECTION_PASS")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["selftest","once"])
    args=parser.parse_args()
    if args.action=="selftest":
        selftest()
        return
    if os.geteuid()!=0:
        raise SystemExit("SAFE_STOP_ROOT_REQUIRED")
    # DSM may start a second task while first instance is running.
    lock=Path("/volume1/docker/RG_TELEGRAM_NEWS_EXPORT/.rg_health.lock")
    if lock.is_symlink():
        raise SystemExit("SAFE_STOP_LOCK_SYMLINK")
    try:
        fd=os.open(str(lock),os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
        with os.fdopen(fd,"w") as stream:
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=tick()
            print(json.dumps(result,sort_keys=True))
    except (OSError,SafeStop,BlockingIOError):
        print('{"status":"SAFE_STOP","publications":0}')
        raise SystemExit(2)

if __name__=="__main__":
    main()
