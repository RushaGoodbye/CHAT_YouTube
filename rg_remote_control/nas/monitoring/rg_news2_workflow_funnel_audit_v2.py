#!/usr/bin/env python3
"""Read-only, aggregate-only NEWS2 moderation/publishing funnel audit.

Never calls Telegram, Cloudflare, Docker, or DSM task runners. Does not publish,
acknowledge, review, restart, create locks or write to SQLite. Reads immutable
SQLite snapshots (which may omit active WAL data) and allowlisted state signals.
Does not reveal captions, photo URLs, chat IDs, bot tokens or any message text.
Python 3.8+.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import stat
import sys
import time

ROOT = pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
DB = "news.sqlite3"
TABLES = ("candidates", "moderation_dispatch", "rg_v35_publications")
STATES = frozenset((
    "pending", "ready", "queued", "sent", "published", "failed", "error",
    "accepted", "accept", "approved", "approve", "rejected", "reject",
    "skipped", "blocked", "new", "review", "reviewed", "done", "completed",
    "in_progress", "processing", "running", "held", "paused", "deferred",
    "retry", "retrying", "delivered", "draft", "unknown", "cancelled",
    "duplicate", "expired", "suppressed", "scheduled", "created", "not_sent",
))
COLUMN_CHOICES = (
    "status", "state", "decision", "action", "moderation_status",
    "delivery_status", "publication_status", "photo_reviewed", "approved",
)
TIME_CHOICES = (
    "updated_at", "created_at", "reviewed_at", "decided_at",
    "published_at", "sent_at", "delivered_at", "last_attempt_at",
)
SCHEMA = "RG_NEWS2_WORKFLOW_FUNNEL_AUDIT_V2"
MAX_ROWS = 10000000
SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
UTC = dt.timezone.utc

def find_live_database(root):
    """Select the production DB only under known candidate paths, never backups."""
    for path in (root/DB, root/"data"/DB, root/"db"/DB, root/"state"/DB):
        if path.is_file() and not path.is_symlink():
            return path
    # Existing NEWS2 audit found a live news.sqlite3, possibly nested.
    choices=[]
    if root.is_dir() and not root.is_symlink():
        for parent, dirs, files in os.walk(str(root), followlinks=False):
            depth=len(pathlib.Path(parent).relative_to(root).parts)
            dirs[:]=[n for n in dirs if depth<4 and n.lower() not in (
                "backup", "backups", "archive", "old", "snapshot", "snapshots", "cache",
                "preflight", "secrets", "venv") and not n.startswith(".")
                and not (pathlib.Path(parent)/n).is_symlink()]
            if DB in files:
                p=pathlib.Path(parent)/DB
                if p.is_file() and not p.is_symlink():
                    choices.append(p)
    # Multiple copies exist in legacy NEWS2 layouts: select only an
    # unequivocally fresh DB, never guess between two active databases.
    if len(choices)==1:
        return choices[0]
    if len(choices)>1:
        choices.sort(key=lambda p:p.stat().st_mtime, reverse=True)
        now=time.time()
        latest=choices[0].stat().st_mtime
        next_latest=choices[1].stat().st_mtime
        if -120<=now-latest<=900 and latest-next_latest>=3600:
            return choices[0]
    return None

def quote(identifier):
    if not SAFE_IDENTIFIER.fullmatch(identifier):
        raise ValueError("unsafe SQL identifier")
    return '"' + identifier + '"'

def age_of(path, now):
    try:
        return max(0, int(now.timestamp()-path.stat().st_mtime))
    except OSError:
        return None

def utc_age(value, now):
    """Derive bounded age in seconds without exposing stored timestamps."""
    try:
        if type(value) in (int, float):
            stamp=float(value)
            if stamp > 1e12:
                stamp/=1000.0
            if stamp < 946684800 or stamp > 4102444800:
                return None
            then=dt.datetime.fromtimestamp(stamp, UTC)
        elif isinstance(value,str) and len(value)<42:
            cleaned=value.strip().replace("Z","+00:00")
            then=dt.datetime.fromisoformat(cleaned)
            if then.tzinfo is None:
                return None
            then=then.astimezone(UTC)
        else:
            return None
        seconds=int((now-then).total_seconds())
        return seconds if -120<=seconds<=365*86400 else None
    except (ValueError, OverflowError, OSError, TypeError):
        return None

def table_summary(connection, table, now):
    quoted=quote(table)
    columns=[str(row[1]) for row in connection.execute("PRAGMA table_info("+quoted+")")]
    available=set(columns)
    summary={"present":True,"rows":None,
             "status_counts":{},"status_columns":[],
             "latest_event_age_sec":None,"latest_event_field":None}
    try:
        count=connection.execute("SELECT COUNT(*) FROM "+quoted).fetchone()[0]
        summary["rows"]=int(count) if 0<=count<=MAX_ROWS else None
    except sqlite3.Error:
        summary["rows"]=None
    for col in COLUMN_CHOICES:
        if col not in available:
            continue
        summary["status_columns"].append(col)
        try:
            rows=connection.execute("SELECT "+quote(col)+", COUNT(*) FROM "+quoted+
                                    " GROUP BY "+quote(col)+" LIMIT 120").fetchall()
            counts={}
            unknown=0
            for val, cnt in rows:
                label=str(val).strip().lower() if val is not None else "null"
                if label in STATES:
                    counts[label]=counts.get(label,0)+int(cnt)
                elif type(val) in (bool,int) and val in (0,1):
                    counts["true" if val else "false"]=counts.get("true" if val else "false",0)+int(cnt)
                else:
                    unknown+=int(cnt)
            if unknown:
                counts["other_redacted"]=unknown
            summary["status_counts"][col]=counts
        except sqlite3.Error:
            summary["status_counts"][col]={"query_unavailable":True}
    for col in TIME_CHOICES:
        if col not in available:
            continue
        try:
            value=connection.execute("SELECT MAX("+quote(col)+") FROM "+quoted).fetchone()[0]
            age=utc_age(value,now)
            if age is not None:
                summary["latest_event_age_sec"]=age
                summary["latest_event_field"]=col
                break
        except sqlite3.Error:
            continue
    return summary

def db_summary(path, now):
    if path is None:
        return {"found":False,"reason":"missing_or_ambiguous_live_database"}
    out={"found":True,"db_basename":DB,"age_sec":age_of(path,now),
         "immutable_read_only":True,"wal_present":path.with_name(DB+"-wal").exists(),
         "wal_changes_may_be_omitted":path.with_name(DB+"-wal").exists(),
         "quick_check":"unavailable","tables":{}}
    if path.stat().st_size>20*1024*1024*1024:
        out["reason"]="database_too_large_to_audit"
        return out
    try:
        conn=sqlite3.connect(path.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
        begun=time.monotonic()
        conn.set_progress_handler(lambda:1 if time.monotonic()-begun>3.0 else 0,3000)
        try:
            conn.execute("PRAGMA query_only=ON")
            row=conn.execute("PRAGMA quick_check(1)").fetchone()
            out["quick_check"]="ok" if row and row[0]=="ok" else "error"
            present={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in TABLES:
                out["tables"][table]=table_summary(conn,table,now) if table in present else {"present":False}
        finally:
            conn.close()
    except (sqlite3.Error,OSError,ValueError):
        out["reason"]="database_read_failed"
    return out

def signal(root, name, now):
    """Read known JSON files; return only explicitly allowlisted counters/flags."""
    paths=(root/name, root/"runtime"/name, root/"state"/name)
    file=next((p for p in paths if p.is_file() and not p.is_symlink() and p.stat().st_size<2*1024*1024),None)
    if file is None:
        return {"found":False}
    result={"found":True,"age_sec":age_of(file,now),"json_valid":False}
    try:
        doc=json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(doc,dict):
            return result
        result["json_valid"]=True
        fields={}
        for key in ("channel_publications","publications","private_cards_sent",
                    "moderation_cards_sent","accept_count","reject_count",
                    "accept_callbacks","reject_callbacks","callbacks_processed",
                    "accepted_count","rejected_count","pending_count","queue_depth",
                    "sent_count","attempted_count","failed_count",
                    "last_action_acknowledged","second_poller_started",
                    "auto_delivery_enabled","public_channel_enabled","publisher_enabled"):
            value=doc.get(key)
            if type(value) is bool:
                fields[key]=value
            elif type(value) is int and 0<=value<=MAX_ROWS:
                fields[key]=value
        result["allowlisted_fields_unverified"]=fields
    except (OSError,ValueError,TypeError,UnicodeError,json.JSONDecodeError):
        pass
    return result

def main_report(root, now=None):
    now=now or dt.datetime.now(UTC)
    db=db_summary(find_live_database(root),now)
    signals={}
    for name in ("callback_v29_state.json","last_tick.json",
                 "telegram_native_activation_status.json"):
        signals[name]=signal(root,name,now)
    tables=db.get("tables",{})
    candidates=tables.get("candidates",{})
    dispatch=tables.get("moderation_dispatch",{})
    publications=tables.get("rg_v35_publications",{})
    return {
        "schema":SCHEMA,"read_only":True,"telegram_api_calls":0,
        "cloudflare_calls":0,"public_channel_messages_sent":0,
        "db_writes":0,
        "db":db,"signals":signals,
        "candidates_table_available":candidates.get("present") is True,
        "dispatch_table_available":dispatch.get("present") is True,
        "publication_ledger_available":publications.get("present") is True,
        "moderator_button_callbacks_confirmed":"NOT_PROVEN_BY_AGGREGATE_COUNTERS",
        "publisher_uniqueness_confirmed":"NOT_PROVEN",
        "actual_publication_delivery_confirmed":"NOT_PROVEN",
        "publication_gate_must_remain_off":True,
        "note":"Status counts are point-in-time immutable snapshots; WAL may be omitted. Zero processes alone do not prove bot stopped."
    }

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        root=pathlib.Path(directory)
        data=root/"data"
        data.mkdir()
        db=data/DB
        cx=sqlite3.connect(str(db))
        cx.execute("CREATE TABLE candidates(id INTEGER, status TEXT, caption TEXT, created_at TEXT)")
        cx.execute("CREATE TABLE moderation_dispatch(id INTEGER, status TEXT, chat_id TEXT)")
        cx.execute("CREATE TABLE rg_v35_publications(id INTEGER, status TEXT, access_token TEXT)")
        cx.executemany("INSERT INTO candidates VALUES (?,?,?,?)",[
            (1,"pending","SECRET_CAPTION","2026-10-24T15:00:00+00:00"),
            (2,"accepted","PRIVATE_TEXT","2026-10-25T18:00:00+00:00"),
            (3,"unrecognized_private_text","PRIVATE_TEXT","2026-10-25T18:10:00+00:00")])
        cx.execute("INSERT INTO moderation_dispatch VALUES(1,'sent','PRIVATE_CHAT_ID')")
        cx.execute("INSERT INTO rg_v35_publications VALUES(1,'blocked','TOKEN_PRIVATE')")
        cx.commit();cx.close()
        (root/"callback_v29_state.json").write_text(json.dumps({
            "callbacks_processed":5,"chat_id":"PRIVATE_CHAT_ID",
            "bot_token":"TOKEN_PRIVATE","accept_count":2}),encoding="utf-8")
        now=dt.datetime(2026,10,25,19,0,tzinfo=UTC)
        doc=main_report(root,now)
        assert doc["db"]["quick_check"]=="ok"
        assert doc["db"]["tables"]["candidates"]["rows"]==3
        assert doc["db"]["tables"]["candidates"]["status_counts"]["status"]["pending"]==1
        assert doc["db"]["tables"]["candidates"]["status_counts"]["status"]["other_redacted"]==1
        assert doc["signals"]["callback_v29_state.json"]["allowlisted_fields_unverified"]["callbacks_processed"]==5
        assert doc["moderator_button_callbacks_confirmed"]=="NOT_PROVEN_BY_AGGREGATE_COUNTERS"
        printed=json.dumps(doc)
        for secret in ("SECRET_CAPTION","PRIVATE_TEXT","PRIVATE_CHAT_ID","TOKEN_PRIVATE",
                       "unrecognized_private_text"):
            assert secret not in printed, secret
        assert doc["db"]["immutable_read_only"] is True
        # A stale duplicate can be distinguished from the active DB.
        old_dir=root/"legacy"
        old_dir.mkdir()
        old_file=old_dir/DB
        import shutil
        shutil.copyfile(str(db),str(old_file))
        os.utime(str(old_file),(time.time()-86400,time.time()-86400))
        assert find_live_database(root)==db
        old_file.touch()
        assert find_live_database(root) is None
        assert doc["publication_gate_must_remain_off"] is True
    print("RG_NEWS2_FUNNEL_AUDIT_V2_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",nargs="?",choices=("diagnose","selftest"),default="diagnose")
    parser.add_argument("--root",default=str(ROOT))
    args=parser.parse_args()
    if args.mode=="selftest":
        selftest()
    else:
        print(json.dumps(main_report(pathlib.Path(args.root)),indent=2,sort_keys=True,ensure_ascii=False))
