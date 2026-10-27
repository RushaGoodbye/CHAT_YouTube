#!/usr/bin/env python3
"""NEWS RG post-repair read-only pulse for private photo moderation.

One command; no Telegram API, no pollers, no publishing, no SQLite writes,
no running scheduler tasks, no imports of production code.
"""
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
CAPACITY=3
REPAIR_BASELINE_RECEIPTS=5

def utc_epoch(v):
    if v is None:return None
    if isinstance(v,(int,float)):
        x=float(v)
        if x>1e12:x/=1000
        return x if 946684800<x<4102444800 else None
    if isinstance(v,str):
        try:
            d=dt.datetime.fromisoformat(v.replace("Z","+00:00"))
            if d.tzinfo is None:d=d.replace(tzinfo=dt.timezone.utc)
            return d.timestamp()
        except (ValueError,OverflowError):return None
    return None

def sqlite_pulse(root):
    db=root/"news.sqlite3"
    if not db.is_file() or db.is_symlink():raise RuntimeError("DATABASE_INVALID")
    cx=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
    cx.execute("PRAGMA query_only=ON")
    try:
        schema={r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"candidates","rg_news2_photo_dispatch"}.issubset(schema):
            raise RuntimeError("REQUIRED_TABLES_MISSING")
        dcols={r[1] for r in cx.execute('PRAGMA table_info("rg_news2_photo_dispatch")')}
        ccols={r[1] for r in cx.execute('PRAGMA table_info("candidates")')}
        if not {"candidate_id","telegram_message_id"}.issubset(dcols) or \
           not {"id","photo_reviewed","status"}.issubset(ccols):
            raise RuntimeError("SCHEMA_NOT_RECOGNIZED")
        receipts,rows=cx.execute("SELECT COUNT(telegram_message_id),COUNT(*) "
                                "FROM rg_news2_photo_dispatch").fetchone()
        pending=cx.execute("SELECT COUNT(*) FROM candidates "
                           "WHERE status='awaiting_photo_review'").fetchone()[0]
        open_cards=cx.execute(
           "SELECT COUNT(*) FROM rg_news2_photo_dispatch d "
           "JOIN candidates c ON c.id=d.candidate_id "
           "WHERE d.telegram_message_id IS NOT NULL "
           "AND COALESCE(c.photo_reviewed,0)=0").fetchone()[0]
        last=None
        sent24=None
        if "updated_at" in dcols:
            times=[utc_epoch(r[0]) for r in cx.execute(
                "SELECT updated_at FROM rg_news2_photo_dispatch "
                "WHERE telegram_message_id IS NOT NULL")]
            times=[x for x in times if x is not None]
            if times:
                last=round(max(0,time.time()-max(times))/60,1)
                sent24=sum(0<=time.time()-x<=86400 for x in times)
        audited=cx.execute("SELECT COUNT(*) FROM rg_v35_photo_audit").fetchone()[0] \
            if "rg_v35_photo_audit" in schema else None
        return {"confirmed_photo_receipts":receipts,
                "dispatch_rows":rows,"unreceipted_dispatch_rows":rows-receipts,
                "queued_photo_review":pending,
                "unreviewed_delivered_cards":open_cards,
                "free_moderation_slots":max(0,CAPACITY-open_cards),
                "last_photo_receipt_age_minutes":last,
                "photo_receipts_in_last_24h_by_dispatch_update":sent24,
                "photo_audit_rows":audited}
    finally:cx.close()

def sched_status():
    path=next((p for p in ("/usr/syno/bin/synoschedtask",
                          "/usr/syno/sbin/synoschedtask") if os.path.isfile(p)),None)
    if not path:return {"available":False}
    try:
        p=subprocess.run([path,"--get"],stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,timeout=15)
    except (OSError,subprocess.TimeoutExpired):
        return {"available":False}
    if p.returncode!=0:return {"available":False}
    fields={};idx=None
    for line in p.stdout.decode("utf-8","replace").splitlines():
        m=re.match(r"^\s*(ID|State|Status|Last Run Time|Command)\s*:\s*\[?(.*?)\]?\s*$",
                   line,re.I)
        if not m:continue
        key=m.group(1).lower();val=m.group(2).rstrip(" ]")
        if key=="id":
            idx=int(val) if val.isdigit() else None
            continue
        if idx==4:fields[key]=val
    if not fields:return {"available":True,"task4_found":False}
    ans={"available":True,"task4_found":True,
         "enabled":fields.get("state","").lower()=="enabled",
         "last_status":fields.get("status","").lower(),
         "script_matches":"rg_news_dsm_tick.sh" in fields.get("command","")}
    try:
        t=dt.datetime.strptime(fields["last run time"],"%a %b %d %H:%M:%S %Y")
        ans["last_execution_age_minutes"]=round(
             max(0,(dt.datetime.now()-t).total_seconds())/60,1)
    except (KeyError,ValueError):pass
    return ans

def inspect(root=ROOT,vault=VAULT,schedule=None):
    d=sqlite_pulse(root)
    guard=root/"rg_news2_private_final_guard_v1.py"
    tick=root/"rg_news_dsm_tick.sh"
    patched=(guard.is_file() and not guard.is_symlink() and
             "rg_capacity_relax_exact" in guard.read_text(encoding="utf-8")
             and "PRIVATE_PHOTO_REVIEW_CAPACITY_3" in
                 guard.read_text(encoding="utf-8"))
    installed=(tick.is_file() and not tick.is_symlink() and
               "RG_NEWS2_PRIVATE_FINAL_V1" in tick.read_text(encoding="utf-8"))
    marker=vault/"rg_news2_private_final_unconfirmed_v1.json"
    if marker.is_symlink():raise RuntimeError("UNCERTAINTY_MARKER_SYMLINK")
    uncertain=marker.is_file()
    scheduler=sched_status() if schedule is None else schedule
    latest=d["confirmed_photo_receipts"]
    if uncertain or d["unreceipted_dispatch_rows"]:
        verdict="BLOCKED_UNCONFIRMED_SEND_DO_NOT_RETRY"
    elif not patched or not installed:
        verdict="INSTALLED_SENDER_SOURCE_NOT_VERIFIED"
    elif d["unreviewed_delivered_cards"]>=CAPACITY:
        verdict="MODERATION_CAPACITY_FULL_REVIEW_CARDS"
    elif latest<REPAIR_BASELINE_RECEIPTS:
        verdict="REPAIR_RECEIPT_NOT_CONFIRMED"
    elif latest==REPAIR_BASELINE_RECEIPTS:
        verdict="FIRST_REPAIR_CARD_CONFIRMED_NEXT_SCHEDULED_SEND_NOT_YET_PROVEN"
    else:
        verdict="ADDITIONAL_PRIVATE_RECEIPT_AFTER_REPAIR"
    return {"schema":"RG_NEWS2_AFTER_REPAIR_PULSE_V1",
            "read_only":True,"telegram_calls":0,"db_writes":0,
            "pollers_started":0,"publications":0,
            "database":d,"patched_guard_present":patched,
            "existing_dsm_hook":installed,
            "new_uncertainty_marker":uncertain,
            "scheduler":scheduler,
            "verdict":verdict,
            "automatic_scheduler_causality_proven":False}

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)/"nas";root.mkdir()
        vault=pathlib.Path(td)/"vault";vault.mkdir()
        (root/"rg_news2_private_final_guard_v1.py").write_text(
            "# rg_capacity_relax_exact PRIVATE_PHOTO_REVIEW_CAPACITY_3")
        (root/"rg_news_dsm_tick.sh").write_text("# RG_NEWS2_PRIVATE_FINAL_V1")
        cx=sqlite3.connect(str(root/"news.sqlite3"))
        cx.execute("CREATE TABLE candidates(id INTEGER PRIMARY KEY,"
                   "status TEXT,photo_reviewed INT)")
        cx.execute("CREATE TABLE rg_news2_photo_dispatch("
                   "candidate_id INT,telegram_message_id INT,updated_at TEXT)")
        cx.executemany("INSERT INTO candidates VALUES(?,?,?)",
                       [(i,"awaiting_moderation",int(i<5)) for i in range(1,6)])
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        cx.executemany("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?)",
                       [(i,i+10,now) for i in range(1,6)])
        cx.commit();cx.close()
        sample={"available":True,"task4_found":True,"enabled":True,
                "last_status":"success","script_matches":True}
        r=inspect(root,vault,sample)
        assert r["verdict"].startswith("FIRST_REPAIR_CARD_CONFIRMED")
        assert r["database"]["free_moderation_slots"]==2
        cx=sqlite3.connect(str(root/"news.sqlite3"))
        cx.execute("INSERT INTO candidates VALUES(6,'awaiting_moderation',1)")
        cx.execute("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?)",(6,16,now))
        cx.commit();cx.close()
        assert inspect(root,vault,sample)["verdict"]=="ADDITIONAL_PRIVATE_RECEIPT_AFTER_REPAIR"
        (vault/"rg_news2_private_final_unconfirmed_v1.json").write_text("{}")
        assert inspect(root,vault,sample)["verdict"]=="BLOCKED_UNCONFIRMED_SEND_DO_NOT_RETRY"
        (vault/"rg_news2_private_final_unconfirmed_v1.json").unlink()
        cx=sqlite3.connect(str(root/"news.sqlite3"))
        cx.execute("INSERT INTO candidates VALUES(7,'awaiting_moderation',0)")
        cx.execute("INSERT INTO candidates VALUES(8,'awaiting_moderation',0)")
        cx.execute("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?)",(7,17,now))
        cx.execute("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?)",(8,18,now))
        cx.commit();cx.close()
        assert inspect(root,vault,sample)["verdict"]=="MODERATION_CAPACITY_FULL_REVIEW_CARDS"
    print("RG_NEWS2_AFTER_REPAIR_PULSE_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(inspect(),sort_keys=True,ensure_ascii=False,indent=2))
    else:sys.exit("Only selftest or inspect supported")
