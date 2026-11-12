#!/usr/bin/env python3
"""Prepare minimal sanitized NAS Telegram health metadata.

Run only from a trusted NAS operator context, not from GitHub runner.
This module never opens any operator file or reads Telegram credentials.
It only stats allowlisted locations, emits no filenames or private paths,
and writes the resulting JSON to a dedicated non-secret export directory.
Actual NAS installation is deliberately separate.
"""
import argparse
import json
import os
import pathlib
import stat
import tempfile
import time

SCHEMA="RG_NEWS_NAS_SANITIZED_EXPORT_V1"
# No file contents are accessed, even for JSON or log records.
ALLOWLIST={
    "operator": "operator",
    "review_staging": "operator/news_rg_private_review_staging",
    "private_receipts": "operator/news_rg_private_multipart_receipts_v1",
    "editorial_decisions": "operator/news_rg_editorial_decisions_v1",
    "watermark_handoff": "operator/news_rg_video_watermark_handoff_v1",
}
class ExportError(ValueError):pass

def summarize(base, now=None):
    base=pathlib.Path(base)
    if base.is_symlink() or not base.is_dir():
        raise ExportError("UNSAFE_BASE")
    ts=int(time.time() if now is None else now)
    if type(ts) is not int or ts<1:raise ExportError("INVALID_TIMESTAMP")
    records={}
    for label,relative in ALLOWLIST.items():
        path=base/relative
        try:
            info=path.lstat()
        except FileNotFoundError:
            records[label]={"exists":False}
            continue
        except OSError:
            records[label]={"exists":False,"stat_error":True}
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ExportError("SYMLINK_PATH_"+label.upper())
        if not stat.S_ISDIR(info.st_mode):
            raise ExportError("NON_DIRECTORY_"+label.upper())
        records[label]={"exists":True,"directory":True}
    return {"schema":SCHEMA,"generated_at_unix":ts,
            "contains_secrets":False,"private_messages_read":0,
            "telegram_api_calls":0,"publications":0,
            "source":"LOCAL_NAS_METADATA_ONLY","locations":records}

def export_report(report,dest):
    dest=pathlib.Path(dest)
    # Export only into an existing dedicated directory, never into operator.
    parent=dest.parent
    if parent.is_symlink() or not parent.is_dir() or dest.name!="rg_news_health_public.json":
        raise ExportError("UNSAFE_EXPORT_PATH")
    if parent.stat().st_mode & 0o022:
        raise ExportError("EXPORT_DIRECTORY_GROUP_WORLD_WRITABLE")
    if dest.is_symlink():raise ExportError("SYMLINK_EXPORT")
    if dest.exists() and not dest.is_file():raise ExportError("UNSAFE_EXPORT_TARGET")
    if dest.exists() and (dest.stat().st_mode & 0o022):
        raise ExportError("EXPORT_TARGET_GROUP_WORLD_WRITABLE")
    data=json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n"
    fd,temp=tempfile.mkstemp(prefix=".rg_news_health_",dir=str(parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            os.fchmod(stream.fileno(),0o644)
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,dest)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return {"status":"EXPORTED_METADATA_ONLY","contains_secrets":False}

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        base=root/"source";base.mkdir()
        (base/"operator").mkdir()
        (base/"operator"/"news_rg_private_review_staging").mkdir()
        export=root/"export";export.mkdir()
        report=summarize(base,now=1762963000)
        assert report["locations"]["operator"]["exists"]
        assert not report["locations"]["private_receipts"]["exists"]
        assert report["private_messages_read"]==0
        target=export/"rg_news_health_public.json"
        export_report(report,target)
        stored=json.loads(target.read_text(encoding="utf-8"))
        assert stored==report
        assert "operator/" not in target.read_text()
        bad=base/"operator"/"news_rg_private_multipart_receipts_v1"
        bad.symlink_to(base/"operator")
        try:summarize(base,now=1762963000)
        except ExportError as e:assert str(e)=="SYMLINK_PATH_PRIVATE_RECEIPTS"
        else:raise AssertionError("SYMLINK_NOT_REJECTED")
        open_dir=root/"open_export";open_dir.mkdir(mode=0o777)
        open_dir.chmod(0o777)
        try:export_report(report,open_dir/"rg_news_health_public.json")
        except ExportError as e:assert str(e)=="EXPORT_DIRECTORY_GROUP_WORLD_WRITABLE"
        else:raise AssertionError("OPEN_EXPORT_DIRECTORY_ACCEPTED")
        try:export_report(report,export/"wrong_name.json")
        except ExportError as e:assert str(e)=="UNSAFE_EXPORT_PATH"
        else:raise AssertionError("WRONG_EXPORT_ALLOWED")
    print("SANITIZED_EXPORT_READS_NO_PRIVATE_FILES_PASS")
    print("SANITIZED_EXPORT_ATOMIC_OUTPUT_PASS")
    print("SANITIZED_EXPORT_SYMLINK_GUARD_PASS")
    print("SANITIZED_EXPORT_ALLOWLIST_PASS")
    print("SANITIZED_EXPORT_DIRECTORY_PERMISSIONS_PASS")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("action",choices=["selftest","export"])
    ap.add_argument("--base",default="/volume1/docker/RG_TELEGRAM_NEWS_2")
    ap.add_argument("--out",default="/volume1/docker/RG_TELEGRAM_NEWS_EXPORT/rg_news_health_public.json")
    args=ap.parse_args()
    if args.action=="selftest":selftest();return
    # No directory creation or permission changes. Owner must separately
    # provision a non-secret export directory with least privilege.
    try:
        result=export_report(summarize(args.base),args.out)
        print(json.dumps(result,sort_keys=True))
    except (ExportError,OSError,ValueError):
        print('{"status":"SAFE_STOP","secrets_read":false,"publications":0}')
        raise SystemExit(2)
if __name__=="__main__":main()
