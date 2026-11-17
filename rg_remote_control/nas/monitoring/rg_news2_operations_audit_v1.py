#!/usr/bin/env python3
"""NEWS2 read-only operations audit.

A narrow diagnostic for existing private moderation and NEWS2 intake.
Does not invoke the Telegram API, Cloudflare, schedulers or any application
scripts. Never reads or outputs chat text, captions, credentials or full logs.
SQLite is opened with immutable=1 (does NOT incorporate active WAL changes).
Compatible with Synology Python 3.8+.
"""
from __future__ import print_function
import argparse
import datetime
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter

NEWS="RG_TELEGRAM_NEWS_2"
ROOT="/volume1/docker"
ALLOWED_STATUS={"ok","success","error","failed","pending","ready","approved",
                "rejected","accepted","declined","queued","sent","published",
                "blocked","moderation","done","review","unreviewed",
                "running","idle","deferred","skipped","completed"}
DB_NAMES=("candidates","moderation","queue","outbox","publications","messages","posts")
SECRET_TERMS=("secret","token","password","credentials","private","session","auth","chat_id","api_key")
CB_FILES=("callback_v29_state.json","callback_v29.log")
TICK_FILES=("last_tick.json","outbound_tick.log")
SAFE_BASENAME=re.compile(r"^[a-zA-Z0-9_.-]{1,96}$")
UTC=datetime.timezone.utc

def age_sec(path, now=None):
    now=now or time.time()
    try:
        return max(0,int(now-path.stat().st_mtime))
    except OSError:
        return None

def find_named(root, filenames, maxdepth=5, limit=24):
    found=[]
    if not root.is_dir() or root.is_symlink():
        return found
    for parent,dirs,files in os.walk(str(root),followlinks=False):
        depth=len(pathlib.Path(parent).relative_to(root).parts)
        dirs[:]=[d for d in dirs if depth<maxdepth and not d.startswith(".") and
                 d.lower() not in ("backups","backup","cache","secrets","venv") and
                 not (pathlib.Path(parent)/d).is_symlink()]
        for name in filenames:
            if name not in files:
                continue
            file=pathlib.Path(parent)/name
            try:
                if not file.is_symlink() and file.is_file() and file.stat().st_size<5*1024*1024:
                    found.append(file)
            except OSError:
                pass
            if len(found)>=limit:
                return found
    return found

def safe_json_health(path):
    result={"json_valid":False,"status":"unknown"}
    try:
        with path.open(encoding="utf-8") as stream:
            payload=json.load(stream)
        if not isinstance(payload,dict):
            return result
        result["json_valid"]=True
        for name in ("status","state","outcome"):
            val=payload.get(name)
            if isinstance(val,str) and val.lower() in ALLOWED_STATUS:
                result["status"]=val.lower()
                break
        # Numbers and booleans only, names strictly allowlisted.
        flags={}
        for key in ("polls","messages_sent","channel_publications","success","ok",
                    "second_poller_started","publishing_enabled","moderator_action_required"):
            value=payload.get(key)
            if type(value) is bool:
                flags[key]=value
            elif type(value) is int and 0<=value<=10000000:
                flags[key]=value
        if flags:
            result["reported_fields_unverified"]=flags
    except (OSError,ValueError,UnicodeError,TypeError,json.JSONDecodeError):
        pass
    return result

def file_activity(root, files, now):
    candidates=find_named(root,files)
    output={}
    for name in files:
        hits=[p for p in candidates if p.name==name]
        hits.sort(key=lambda p:age_sec(p,now) if age_sec(p,now) is not None else 99999999)
        row={"found":bool(hits),"matching_files":len(hits)}
        if hits:
            row["age_sec"]=age_sec(hits[0],now)
            row["fresh_10m"]=row["age_sec"] is not None and row["age_sec"]<=600
            if name.endswith(".json"):
                row.update(safe_json_health(hits[0]))
        output[name]=row
    return output

def process_counts():
    """Only report command basename match counts. Never show any process argv."""
    try:
        cp=subprocess.run(["ps","-eo","args"],stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,text=True,timeout=4)
        if cp.returncode:
            return {"available":False}
        rows=cp.stdout.splitlines()[1:]
    except (OSError,subprocess.TimeoutExpired):
        return {"available":False}
    names=("callback_v29.py","rg_news_dsm_tick.sh","outbound_tick.sh",
           "rg_nas_telegram_nas_native_bot_v01.py")
    counts={}
    for name in names:
        # Explicit process basename boundary; avoid matching temp audit command.
        pattern=re.compile(r"(?<![A-Za-z0-9_.-])"+re.escape(name)+r"(?![A-Za-z0-9_.-])")
        counts[name]=sum(bool(pattern.search(row)) for row in rows)
    return {"available":True,"process_match_counts_not_unique_pollers":counts}

def db_inventory(root, now, limit=8):
    paths=[]
    if root.is_dir():
        for parent, dirs, files in os.walk(str(root),followlinks=False):
            depth=len(pathlib.Path(parent).relative_to(root).parts)
            dirs[:]=[d for d in dirs if depth<5 and not d.startswith(".") and
                     d.lower() not in ("backup","backups","secrets","venv","cache") and
                     not (pathlib.Path(parent)/d).is_symlink()]
            for name in files:
                low=name.lower()
                if not SAFE_BASENAME.fullmatch(name) or any(x in low for x in SECRET_TERMS):
                    continue
                if not low.endswith((".db",".sqlite",".sqlite3")):
                    continue
                p=pathlib.Path(parent)/name
                try:
                    if not p.is_symlink() and p.stat().st_size>0:
                        paths.append(p)
                except OSError:
                    pass
    paths.sort(key=lambda p:(not any(t in p.name.lower() for t in DB_NAMES),
                             age_sec(p,now) if age_sec(p,now) is not None else 99999999))
    out=[]
    for p in paths[:limit]:
        item={"basename":p.name,"age_sec":age_sec(p,now),
              "immutable_snapshot":True,"wal_changes_may_be_excluded":p.with_name(p.name+"-wal").exists(),
              "integrity":"unavailable","tables":[]}
        try:
            cx=sqlite3.connect(p.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=1)
            cx.set_progress_handler(lambda:1 if time.monotonic()-start>0.45 else 0,1000)
            start=time.monotonic()
            try:
                row=cx.execute("PRAGMA quick_check(1)").fetchone()
                item["integrity"]="ok" if row and row[0]=="ok" else "error"
                rowset=cx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                safe_tables=[]
                for row in rowset:
                    name=row[0]
                    if (isinstance(name,str) and SAFE_BASENAME.fullmatch(name)
                        and not any(t in name.lower() for t in SECRET_TERMS)
                        and any(t in name.lower() for t in DB_NAMES)):
                        safe_tables.append(name)
                item["tables"]=sorted(safe_tables)[:15]
                # No SELECT from application tables; counts/actions cannot be
                # verified without knowing the exact live schema.
            finally:
                cx.close()
        except (sqlite3.Error,OSError,ValueError):
            pass
        out.append(item)
    return {"found_total":len(paths),"examined":len(out),"databases":out}

def run(root=pathlib.Path(ROOT),now=None,include_processes=True):
    now=now or time.time()
    news=root/NEWS
    files=file_activity(news,CB_FILES+TICK_FILES,now)
    queue=db_inventory(news,now)
    # Gate state is a boolean path check, never read the secret or cutover file.
    gate=root/"RG_SECRETS"/"rg_nas_telegram_cutover_enabled"
    dsm_tick=files["last_tick.json"]
    callback=files["callback_v29_state.json"]
    return {
        "schema":"RG_NEWS2_OPERATIONS_AUDIT_V1",
        "read_only":True,"telegram_api_calls_by_audit":0,
        "cloudflare_calls_by_audit":0,"public_channel_messages_sent_by_audit":0,
        "data_modifications":0,
        "host_news2_directory_present":news.is_dir(),
        "runtime_files":files,
        "sqlite":queue,
        "process_observations":process_counts() if include_processes else {"skipped":True},
        "native_cutover_gate_present":gate.exists() or gate.is_symlink(),
        "dsm_task4_last_tick_recent":bool(dsm_tick.get("fresh_10m")),
        "callback_state_recent":bool(callback.get("fresh_10m") and callback.get("json_valid")),
        "accept_reject_delivery_confirmation":"UNVERIFIED_WITHOUT_SAFE_ACTION_LEDGER",
        "outbound_delivery_confirmation":"UNVERIFIED_WITHOUT_SAFE_SENT_LEDGER",
        "publication_owner_unique":"UNVERIFIED",
        "minute_silence_enforced":"UNVERIFIED",
        "recommendation":"Do not enable public delivery or start a second poller from this audit."
    }

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        news=root/NEWS
        (news/"runtime").mkdir(parents=True)
        stamp=time.time()
        (news/"runtime"/"callback_v29_state.json").write_text('{"status":"ok","chat_id":9999,"token":"SECRET_NEVER_SHOW"}',encoding="utf-8")
        (news/"runtime"/"last_tick.json").write_text('{"status":"success","headline":"SECRET_NEVER_SHOW"}',encoding="utf-8")
        (news/"runtime"/"callback_v29.log").write_text("PRIVATE_NEWS_TEXT\n",encoding="utf-8")
        (news/"runtime"/"outbound_tick.log").write_text("PRIVATE_NEWS_TEXT\n",encoding="utf-8")
        db=news/"moderation.sqlite"
        conn=sqlite3.connect(str(db))
        conn.execute("CREATE TABLE candidates (id integer PRIMARY KEY, caption text, status text)")
        conn.execute("INSERT INTO candidates (caption,status) VALUES ('SECRET_NEVER_SHOW','pending')")
        conn.commit()
        conn.close()
        output=run(root,now=stamp,include_processes=False)
        assert output["callback_state_recent"] is True
        assert output["dsm_task4_last_tick_recent"] is True
        assert output["sqlite"]["databases"][0]["tables"]==["candidates"]
        assert output["sqlite"]["databases"][0]["integrity"]=="ok"
        assert not output["native_cutover_gate_present"]
        encoded=json.dumps(output)
        assert "SECRET_NEVER_SHOW" not in encoded
        assert "PRIVATE_NEWS_TEXT" not in encoded
        assert "9999" not in encoded
        old=stamp-1200
        os.utime(news/"runtime"/"last_tick.json",(old,old))
        assert run(root,now=stamp,include_processes=False)["dsm_task4_last_tick_recent"] is False
        assert output["outbound_delivery_confirmation"]=="UNVERIFIED_WITHOUT_SAFE_SENT_LEDGER"
    print("RG_NEWS2_OPERATIONS_AUDIT_V1_SELFTEST_PASS")

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("mode",nargs="?",choices=("selftest","diagnose"),default="diagnose")
    cli.add_argument("--root",type=pathlib.Path,default=pathlib.Path(ROOT))
    args=cli.parse_args()
    if args.mode=="selftest":
        selftest()
    else:
        print(json.dumps(run(args.root),sort_keys=True,ensure_ascii=False,indent=2))
