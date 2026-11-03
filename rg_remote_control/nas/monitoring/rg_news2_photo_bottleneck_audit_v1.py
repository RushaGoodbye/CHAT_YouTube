#!/usr/bin/env python3
"""Read-only RG NEWS2 photo-review bottleneck audit (Python 3.8+, no network).

Checks whether the waiting queue has image URL candidates and whether photo
review processing is alive. NEVER approves photos, changes statuses, publishes,
starts another Telegram poller, or outputs captions, URLs, chat IDs or secrets.
SQL connections use immutable=1, query_only=ON; live WAL changes may be absent.
"""
import argparse
import ast
import collections
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
import urllib.parse

ROOT = pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
DATABASE = "news.sqlite3"
UTC = dt.timezone.utc
STAGES = {
    "awaiting_photo_review", "awaiting_moderation", "rejected",
    "approved", "accepted", "moderation_ready", "pending",
}
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9_.-]{1,110}$")
COLS = ("status", "photo_reviewed", "photo_url", "image_url",
        "photo_review_note", "created_at", "updated_at")
IGNORED_DIRS = {"backup", "backups", "archive", "archives", "tmp",
                "secrets", "venv", "__pycache__", "cache", "old",
                "snapshot", "snapshots"}
NEEDLES = ("photo", "image", "review", "vision")
BLOCKED_NAME = ("secret", "token", "password", "credential", "env", "session", "chat_id")
MAX_ROWS = 25000

def normalize_status(raw):
    if not isinstance(raw, str):
        return "other_redacted"
    value = raw.strip().lower()
    if value in STAGES:
        return value
    if re.fullmatch(r"[a-z][a-z0-9_]{1,39}", value) and (
        value.startswith(("awaiting_", "photo_", "moderation_", "review_"))
        or value.endswith(("_review", "_rejected", "_ready", "_failed"))):
        if not any(w in value for w in ("secret","token","password","chat","text","caption")):
            return value
    # Digest is deliberately withheld; no arbitrary status text leaks out.
    return "other_redacted"

def age_from(value, now):
    try:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            v = float(value)
            if v > 1e12:
                v /= 1000
            if not 946684800 <= v <= 4102444800:
                return None
            parsed = dt.datetime.fromtimestamp(v, tz=UTC)
        elif isinstance(value, str) and len(value) <= 42:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                # Local timestamps have uncertain timezone and are not assumed UTC.
                return None
            parsed = parsed.astimezone(UTC)
        else:
            return None
        seconds = int((now-parsed).total_seconds())
        return seconds if -120 <= seconds <= 366*86400 else None
    except (ValueError, OverflowError, OSError, TypeError):
        return None

def photo_note_category(value):
    """Finite diagnostics only. The source note itself is NEVER output."""
    if not isinstance(value,str) or not value.strip():
        return "blank"
    note=value.strip().lower()
    rules=(
        ("provider_throttled_or_quota",("429","rate limit","quota","budget","cooldown","лимит","ліміт","квота")),
        ("network_or_fetch_failed",("timeout","timed out","connection","dns","fetch","download","http 403","http 404","403","404","503","network")),
        ("missing_or_bad_image",("missing","no image","no photo","need original photo","original image needed","invalid photo","invalid image","без фото","нема фото")),
        ("manual_review_requested",("manual","human","operator","модератор","ручн","review required")),
        ("image_decode_or_format",("decode","format","corrupt","unsupported","resize")),
        ("image_mismatch",("mismatch","not relevant","невідповід","не відповіда")),
    )
    for label,patterns in rules:
        if any(pattern in note for pattern in patterns):
            return label
    return "other_redacted_note"

def image_quality_class(value):
    if not isinstance(value, str) or not value.strip():
        return "empty"
    val=value.strip()
    if len(val)>2000:
        return "invalid"
    try:
        p=urllib.parse.urlsplit(val)
        if p.scheme.lower() in ("http","https") and p.hostname and not p.username and not p.password:
            return "remote_url_present_unverified"
    except ValueError:
        pass
    return "invalid"

def locate_db(root):
    candidates=[root/DATABASE, root/"data"/DATABASE, root/"db"/DATABASE, root/"state"/DATABASE]
    for p in candidates:
        if p.is_file() and not p.is_symlink():
            return p
    matches=[]
    if not root.is_dir() or root.is_symlink():
        return None
    for parent, dirs, files in os.walk(str(root),followlinks=False):
        depth=len(pathlib.Path(parent).relative_to(root).parts)
        dirs[:]=[d for d in dirs if depth<4 and d.lower() not in IGNORED_DIRS
                 and not d.startswith(".") and not (pathlib.Path(parent)/d).is_symlink()]
        if DATABASE in files:
            p=pathlib.Path(parent)/DATABASE
            if p.is_file() and not p.is_symlink():
                matches.append(p)
    # Never silently pick a backup database.
    return matches[0] if len(matches)==1 else None

def db_photo_counts(root, now):
    p=locate_db(root)
    if p is None:
        return {"available":False,"reason":"db_missing_or_ambiguous"}
    result={"available":True, "database_basename":DATABASE,
            "database_age_sec":max(0,int(now.timestamp()-p.stat().st_mtime)),
            "wal_present":p.with_name(DATABASE+"-wal").exists(),
            "immutable_snapshot":True,"photo_column":None,
            "rows_inspected":0,"total_rows":None,"truncated":False,
            "stages":{},"integrity":"unknown"}
    try:
        cx=sqlite3.connect(p.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
        start=time.monotonic()
        cx.set_progress_handler(lambda:1 if time.monotonic()-start>4.5 else 0,3000)
        try:
            cx.execute("PRAGMA query_only=ON")
            ck=cx.execute("PRAGMA quick_check(1)").fetchone()
            result["integrity"]="ok" if ck and ck[0]=="ok" else "error"
            cols={row[1] for row in cx.execute('PRAGMA table_info("candidates")')}
            if "status" not in cols:
                result["reason"]="candidate_status_column_missing"
                return result
            result["total_rows"]=cx.execute('SELECT COUNT(*) FROM "candidates"').fetchone()[0]
            image_col=next((col for col in ("photo_url","image_url") if col in cols),None)
            result["photo_column"]=image_col
            valid=[c for c in COLS if c in cols]
            query="SELECT "+", ".join('"'+c+'"' for c in valid)+' FROM "candidates" LIMIT '+str(MAX_ROWS)
            out=collections.defaultdict(lambda:{"total":0,"reviewed_true":0,"reviewed_false":0,
                "photo_url_class":collections.Counter(),"photo_review_note_nonempty":0,
                "photo_review_note_categories":collections.Counter(),
                "updated_1h":0,"updated_24h":0,"oldest_age_days":None,
                "latest_age_seconds":None})
            for row in cx.execute(query):
                record=dict(zip(valid,row))
                status=normalize_status(record.get("status"))
                summary=out[status]
                summary["total"]+=1
                if record.get("photo_reviewed") in (1,True):
                    summary["reviewed_true"]+=1
                else:
                    summary["reviewed_false"]+=1
                image=record.get(image_col) if image_col else None
                summary["photo_url_class"][image_quality_class(image)]+=1
                note_category=photo_note_category(record.get("photo_review_note"))
                summary["photo_review_note_categories"][note_category]+=1
                if note_category!="blank":
                    summary["photo_review_note_nonempty"]+=1
                age=age_from(record.get("updated_at"),now)
                if age is not None:
                    summary["updated_1h"]+=int(age<=3600)
                    summary["updated_24h"]+=int(age<=86400)
                    summary["oldest_age_days"]=max(summary["oldest_age_days"] or 0,age//86400)
                    summary["latest_age_seconds"]=min(summary["latest_age_seconds"] if summary["latest_age_seconds"] is not None else age,age)
                result["rows_inspected"]+=1
            result["truncated"]=result["total_rows"]>result["rows_inspected"]
            result["stages"]={key:{**v,
                "photo_url_class":dict(v["photo_url_class"]),
                "photo_review_note_categories":dict(v["photo_review_note_categories"])}
                for key,v in sorted(out.items())}
        finally:
            cx.close()
    except (sqlite3.Error,OSError,ValueError) as err:
        result["reason"]="read_failed_"+type(err).__name__
    return result

def find_photo_worker_files(root, now):
    files=[]
    if not root.is_dir() or root.is_symlink():
        return files
    for parent, dirs, names in os.walk(str(root),followlinks=False):
        depth=len(pathlib.Path(parent).relative_to(root).parts)
        dirs[:]=[d for d in dirs if depth<4 and d.lower() not in IGNORED_DIRS
                 and not d.startswith(".") and not (pathlib.Path(parent)/d).is_symlink()]
        for name in names:
            lower=name.lower()
            if (not SAFE_FILENAME.fullmatch(name) or any(x in lower for x in BLOCKED_NAME)
                or not any(x in lower for x in NEEDLES)
                or not lower.endswith((".py",".sh",".log",".json"))):
                continue
            file=pathlib.Path(parent)/name
            try:
                if not file.is_file() or file.is_symlink():
                    continue
                size=file.stat().st_size
                age=max(0,int(now.timestamp()-file.stat().st_mtime))
                files.append({"name":name,"age_sec":age,"size_bytes":size,
                              "kind":file.suffix.lower()})
            except OSError:
                pass
    files.sort(key=lambda x:x["age_sec"])
    return files[:35]

def check_tick(root, now):
    file=root/"rg_news_dsm_tick.sh"
    out={"found":file.is_file(),"syntax":"not_checked",
         "photo_review_reference":False,"image_reference":False}
    if not file.is_file() or file.is_symlink():
        return out
    try:
        with file.open(encoding="utf-8",errors="replace") as handle:
            code=handle.read(800000)
        out["age_sec"]=max(0,int(now.timestamp()-file.stat().st_mtime))
        out["photo_review_reference"]="photo_review" in code.lower()
        out["image_reference"]=bool(re.search(r"photo|image|vision",code,re.I))
        # Never execute it or echo any shell command/secrets.
        import subprocess
        p=subprocess.run(["/bin/sh","-n",str(file)],stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,timeout=5)
        out["syntax"]="PASS" if p.returncode==0 else "FAIL"
    except (OSError,UnicodeError,subprocess.TimeoutExpired):
        out["syntax"]="UNAVAILABLE"
    return out

def run(root=ROOT,now=None):
    now=now or dt.datetime.now(UTC)
    db=db_photo_counts(root,now)
    worker=find_photo_worker_files(root,now)
    tick=check_tick(root,now)
    waiting=db.get("stages",{}).get("awaiting_photo_review",{})
    images=waiting.get("photo_url_class",{})
    pending=int(waiting.get("total",0))
    observed_valid=images.get("remote_url_present_unverified",0)
    missing=images.get("empty",0)
    return {
        "schema":"RG_NEWS2_PHOTO_BOTTLENECK_AUDIT_V1",
        "read_only":True,"telegram_api_calls":0,
        "cloudflare_calls":0,"sqlite_writes":0,"public_channel_messages_sent":0,
        "all_candidate_media_urls_omitted":True,
        "photo_review_approval_changes":0,
        "photo_queue":db,
        "active_dsm_tick":tick,
        "photo_worker_file_inventory":worker,
        "decision":{
            "pending_photo_review_rows":pending,
            "pending_with_remote_image_url_present_but_unverified":observed_valid,
            "pending_without_photo_url":missing,
            "needs_review_worker_investigation":pending>100 and observed_valid>0,
            "needs_media_acquisition_investigation":pending>100 and missing>0,
            "safe_to_automatically_approve_photos":False,
            "safe_to_enable_public_publication":False,
        },
        "caution":"A URL's presence never proves an image is genuine, accessible or related to the story."
    }

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        folder=root/"data"
        folder.mkdir()
        db=folder/DATABASE
        cx=sqlite3.connect(str(db))
        cx.execute("CREATE TABLE candidates (status TEXT, photo_reviewed INTEGER, photo_url TEXT, photo_review_note TEXT, updated_at TEXT)")
        now=dt.datetime.now(UTC)
        stamp=now.isoformat()
        cx.executemany("INSERT INTO candidates VALUES (?,?,?,?,?)",[
            ("awaiting_photo_review",0,"https://example.org/picture.jpg","",stamp),
            ("awaiting_photo_review",0,"","need original photo",stamp),
            ("awaiting_moderation",1,"https://example.org/safe.jpg","OK",stamp),
            ("TOKEN_PRIVATE",0,"http://127.0.0.1/image","private text",stamp)])
        cx.commit();cx.close()
        (root/"rg_news_dsm_tick.sh").write_text("#!/bin/sh\n# PHOTO REVIEW\nexit 0\n")
        r=run(root,now)
        q=r["photo_queue"]
        assert q["integrity"]=="ok" and q["rows_inspected"]==4
        assert q["stages"]["awaiting_photo_review"]["total"]==2
        assert q["stages"]["awaiting_photo_review"]["photo_url_class"]["empty"]==1
        assert q["stages"]["awaiting_photo_review"]["photo_review_note_categories"]["missing_or_bad_image"]==1
        assert photo_note_category("rate limit provider key=SECRET_NEVER_PRINT")=="provider_throttled_or_quota"
        assert q["stages"]["awaiting_photo_review"]["photo_url_class"]["remote_url_present_unverified"]==1
        assert r["active_dsm_tick"]["syntax"]=="PASS"
        assert r["decision"]["safe_to_automatically_approve_photos"] is False
        raw=json.dumps(r)
        for secret in ("example.org","picture.jpg","safe.jpg","TOKEN_PRIVATE","need original photo"):
            assert secret not in raw
        assert not (root/"RG_NAS_STATE").exists()
    print("RG_NEWS2_PHOTO_BOTTLENECK_AUDIT_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",nargs="?",choices=("selftest","diagnose"),default="diagnose")
    parser.add_argument("--root",type=pathlib.Path,default=ROOT)
    args=parser.parse_args()
    if args.mode=="selftest":
        selftest()
    else:
        print(json.dumps(run(args.root),ensure_ascii=False,sort_keys=True,indent=2))
