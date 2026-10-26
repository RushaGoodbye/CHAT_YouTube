#!/usr/bin/env python3
"""RG NEWS2 BATCH recovery evaluation: backup, private-photo status, route, safety.

ONE NAS CALL. Does not execute any installed service code, send Telegram
messages, start a poller, enable public delivery or modify working DB/scripts.
Creates one new root-owned backup of active files/SQLite and one sanitized
root-owned report. No secret, caption, chat ID, URL, source code or individual
candidate record appears in output.
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
import shutil
import sqlite3
import stat
import sys
import time
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
BACKUPS=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
FILES=("rg_news_dsm_tick.sh","rg_v18.py","telegram_photo_review_flow.py",
       "operator/rg_news2_outbound_queue_v2.py",
       "operator/rg_news2_rss_hourly.py",
       "operator/rg_news2_p31_guarded_callback_once.py")
SENSITIVE=("token","password","secret","chat","user","caption","body",
           "message","url","auth","cookie","email","session","access")
STAGES=("claim_one","deliver_one","send_payload","record_sent",
        "record_uncertain","handle_callback","init_outbox","run","tick")
UTC=dt.timezone.utc

def safe_label(raw):
    if not isinstance(raw,str):
        return "unclassified"
    value=raw.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,43}",value):
        return "unclassified"
    if any(x in value for x in SENSITIVE):
        return "unclassified"
    if value in ("accept","reject","accepted","rejected","sent","queued","pending",
                 "failed","retry","sending","claimed","uncertain","delivered",
                 "completed","blocked","ready","reviewed","skipped"):
        return value
    if value.startswith(("photo_","moderation_","dispatch_","card_","send_",
                         "sent_","awaiting_","review_","retry_","accepted_",
                         "rejected_","delivered_","claimed_","uncertain_")):
        return value
    if value.endswith(("_sent","_ready","_failed","_uncertain","_delivered",
                       "_reviewed","_queued","_claimed","_pending")):
        return value
    return "unclassified"

def age(value):
    try:
        if type(value) in (int,float):
            seconds=float(value)
            if seconds>1e12:seconds/=1000
            if seconds<946684800:return None
            passed=seconds
        elif isinstance(value,str) and len(value)<45:
            stamp=dt.datetime.fromisoformat(value.strip().replace("Z","+00:00"))
            if stamp.tzinfo is None:return None
            passed=stamp.timestamp()
        else:return None
        a=int(time.time()-passed)
        return a if -120<=a<=366*86400 else None
    except (ValueError,OverflowError,TypeError,OSError):
        return None

def parse_source(root):
    result={}
    for rel in FILES:
        p=root/rel
        item={"present":bool(p.is_file() and not p.is_symlink()),"syntax":"UNAVAILABLE"}
        if not item["present"]:
            result[rel]=item;continue
        try:
            if p.stat().st_size>900000:
                item["reason"]="oversized";result[rel]=item;continue
            text=p.read_text(encoding="utf-8",errors="replace")
            item["hash12"]=hashlib.sha256(text.encode()).hexdigest()[:12]
            item["bytes"]=p.stat().st_size
            item["references_legacy"]="rg_v18.py" in text
            item["references_photo"]="telegram_photo_review_flow" in text
            item["references_outbound"]="rg_news2_outbound_queue_v2" in text
            item["mentions_polling"]="getupdates" in text.lower() or "get_updates" in text.lower()
            if rel.endswith(".py"):
                tree=ast.parse(text)
                item["syntax"]="PASS"
                functions={}
                calls=collections.Counter()
                env_names=set()
                for n in ast.walk(tree):
                    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in STAGES:
                        functions[n.name]={"required_args":
                            len(n.args.posonlyargs)+len(n.args.args)-len(n.args.defaults),
                            "if_branches":sum(isinstance(v,ast.If) for v in ast.walk(n))}
                    if isinstance(n,ast.Call):
                        fn=n.func
                        name=fn.id if isinstance(fn,ast.Name) else fn.attr if isinstance(fn,ast.Attribute) else ""
                        if name in STAGES:
                            calls[name]+=1
                        if name in ("getenv","get") and n.args:
                            x=n.args[0]
                            if isinstance(x,ast.Constant) and isinstance(x.value,str):
                                key=x.value
                                if (len(key)<=65 and
                                    re.fullmatch(r"[A-Z][A-Z0-9_]{3,64}",key) and
                                    any(k in key for k in ("PHOTO","MODERAT","DELIVERY","PILOT","RATE"))):
                                    env_names.add(key)
                item["functions"]=functions
                item["calls"]=dict(calls)
                item["configuration_key_names"]=sorted(env_names)[:35]
            else:
                item["syntax"]="PASS_STATIC"
        except (OSError,UnicodeError,ValueError,SyntaxError):
            item["syntax"]="INVALID"
        result[rel]=item
    return result

def database_path(root):
    for p in (root/"news.sqlite3",root/"data/news.sqlite3",
              root/"db/news.sqlite3",root/"state/news.sqlite3"):
        if p.is_file() and not p.is_symlink():return p
    return None

def table_stats(conn,table):
    allowed={"candidates","moderation_dispatch","rg_news2_photo_dispatch",
             "rg_v35_photo_audit"}
    if table not in allowed:
        raise ValueError("table_forbidden")
    q='"'+table+'"'
    cols={r[1] for r in conn.execute("PRAGMA table_info("+q+")")}
    out={"rows":conn.execute("SELECT count(*) FROM "+q).fetchone()[0],
         "states":{},"receipt_nonnull":0,"claim_age_buckets":{},
         "columns":{k:k in cols for k in
                    ("claimed_at","updated_at","telegram_message_id",
                     "photo_reviewed","photo_url","state","status")}}
    for key in ("state","status","outcome"):
        if key not in cols:continue
        found=collections.Counter()
        for v,count in conn.execute('SELECT "'+key+'",COUNT(*) FROM '+q+
                                    ' GROUP BY "'+key+'" LIMIT 150'):
            found[safe_label(v)]+=int(count)
        out["states"][key]=dict(found)
    if "telegram_message_id" in cols:
        out["receipt_nonnull"]=conn.execute(
            'SELECT COUNT(*) FROM '+q+' WHERE "telegram_message_id" IS NOT NULL'
        ).fetchone()[0]
    if "claimed_at" in cols:
        buckets=collections.Counter()
        for (stamp,) in conn.execute('SELECT "claimed_at" FROM '+q+' LIMIT 200'):
            a=age(stamp)
            if a is None:buckets["unknown"]+=1
            elif a<600:buckets["last_10m"]+=1
            elif a<3600:buckets["last_hour"]+=1
            elif a<86400:buckets["last_day"]+=1
            else:buckets["older"]+=1
        out["claim_age_buckets"]=dict(buckets)
    if table=="candidates" and "status" in cols:
        out["awaiting_photo_review"]=conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE status=?",("awaiting_photo_review",)
        ).fetchone()[0]
        if "photo_url" in cols:
            out["waiting_photo_url_present"]=conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE status=? AND photo_url IS NOT NULL AND TRIM(photo_url)<>''",
                ("awaiting_photo_review",)).fetchone()[0]
    return out

def sql_report(db):
    if db is None:
        return {"available":False}
    report={"available":True,"db_age_sec":max(0,int(time.time()-db.stat().st_mtime)),
            "wal_present":db.with_name(db.name+"-wal").exists(),
            "immutable_read_only":True,"tables":{}}
    try:
        cx=sqlite3.connect(db.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
        start=time.monotonic()
        cx.set_progress_handler(lambda:int(time.monotonic()-start>6),2500)
        try:
            cx.execute("PRAGMA query_only=ON")
            known={r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in ("candidates","rg_news2_photo_dispatch",
                         "moderation_dispatch","rg_v35_photo_audit"):
                report["tables"][name]=table_stats(cx,name) if name in known else {"available":False}
        finally:
            cx.close()
    except (sqlite3.Error,OSError,ValueError):
        report["read_failed"]=True
    return report

def report(root=ROOT):
    src=parse_source(root)
    db=sql_report(database_path(root))
    photo=db.get("tables",{}).get("rg_news2_photo_dispatch",{})
    records=photo.get("rows",0)
    receipts=photo.get("receipt_nonnull",0)
    counts=photo.get("states",{}).get("state",{})
    ambiguous=counts.get("unclassified",0)
    legacy=src.get("rg_v18.py",{})
    tick=src.get("rg_news_dsm_tick.sh",{})
    outbound=src.get("operator/rg_news2_outbound_queue_v2.py",{})
    safety={
      "photo_dispatch_rows":records,
      "photo_dispatch_receipts":receipts,
      "dispatch_state_unclassified":ambiguous,
      "legacy_tick_routes_to_outbound_directly":bool(tick.get("references_outbound")),
      "legacy_script_imports_outbound_directly":bool(legacy.get("references_outbound")),
      "outbound_calls_photo_delivery":bool(outbound.get("calls",{}).get("deliver_one")),
      "duplicate_send_risk":bool(records and (ambiguous or receipts)),
      "public_delivery_must_stay_off":True,
      "existing_poller_must_not_be_duplicated":True,
      "auto_photo_approval_permitted":False,
      "safe_to_schedule_new_sender":False,
    }
    return {"schema":"RG_NEWS2_PHOTO_BATCH_RECOVERY_V1",
            "read_only":True,"telegram_requests":0,"db_mutations":0,
            "publications":0,"pollers_started":0,
            "source_contract":src,"sqlite":db,"decision":safety,
            "status":"PREPARED_NO_UNSAFE_LIVE_CHANGES"}

def save_backup(root,report_obj,store):
    if os.geteuid()!=0:
        raise RuntimeError("root_only")
    db=database_path(root)
    if db is None:
        raise RuntimeError("database_missing")
    if not store.is_dir() or store.is_symlink():
        raise RuntimeError("backup_store_missing")
    if any(not report_obj["source_contract"][x]["present"] for x in FILES[:4]):
        raise RuntimeError("source_missing")
    folder=store/("batch-prep-"+dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    folder.mkdir(mode=0o700)
    try:
        for i,rel in enumerate(FILES):
            p=root/rel
            if not p.is_file() or p.is_symlink():continue
            name="source_%02d"%i
            shutil.copyfile(str(p),str(folder/name))
            os.chmod(str(folder/name),0o600)
        source=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)
        target=sqlite3.connect(str(folder/"news.sqlite3"),timeout=3)
        try:source.backup(target,pages=256,sleep=0.02)
        finally:target.close();source.close()
        os.chmod(str(folder/"news.sqlite3"),0o600)
        # The report has only bounded diagnostics and aggregate counters.
        filename=folder/"report.json"
        filename.write_text(json.dumps(report_obj,sort_keys=True,indent=2))
        os.chmod(str(filename),0o600)
        return {"backup_dir":str(folder),"source_backups":len(FILES),
                "database_snapshot":True,"production_code_mutations":0,
                "production_db_mutations":0}
    except Exception:
        shutil.rmtree(str(folder))
        raise

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        (root/"operator").mkdir()
        (root/"rg_news_dsm_tick.sh").write_text("#!/bin/sh\npython3 rg_v18.py\n")
        (root/"rg_v18.py").write_text("def tick():\n    return 1\n")
        (root/"telegram_photo_review_flow.py").write_text(
            "def deliver_one(db, send, chat):\n    return 'sent'\n")
        (root/"operator/rg_news2_outbound_queue_v2.py").write_text(
            "from telegram_photo_review_flow import deliver_one\n"+
            "def run(x):\n    return deliver_one(x, 1, 2)\n")
        cx=sqlite3.connect(str(root/"news.sqlite3"))
        cx.execute("CREATE TABLE rg_news2_photo_dispatch(state text,telegram_message_id int,claimed_at int)")
        cx.executemany("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?)",[
            ("photo_delivered",1,1760000000),("unknown_message_123",2,1760000001)])
        cx.execute("CREATE TABLE candidates(status text, photo_url text)")
        cx.execute("INSERT INTO candidates VALUES('awaiting_photo_review','https://private.example/test')")
        cx.commit();cx.close()
        r=report(root)
        assert r["decision"]["photo_dispatch_receipts"]==2
        assert r["sqlite"]["tables"]["candidates"]["awaiting_photo_review"]==1
        assert r["sqlite"]["tables"]["rg_news2_photo_dispatch"]["states"]["state"]["photo_delivered"]==1
        assert r["sqlite"]["tables"]["rg_news2_photo_dispatch"]["states"]["state"]["unclassified"]==1
        assert not r["decision"]["safe_to_schedule_new_sender"]
        assert "private.example" not in json.dumps(r)
        if os.geteuid()==0:
            place=pathlib.Path(tmp)/"backups"
            place.mkdir(mode=0o700)
            saved=save_backup(root,r,place)
            assert pathlib.Path(saved["backup_dir"]).joinpath("news.sqlite3").is_file()
    print("RG_NEWS2_PHOTO_BATCH_RECOVERY_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("selftest","diagnose","batch"))
    args=parser.parse_args()
    if args.mode=="selftest":selftest();sys.exit(0)
    try:
        doc=report()
        if args.mode=="batch":
            doc["backup"]=save_backup(ROOT,doc,BACKUPS)
        print(json.dumps(doc,sort_keys=True,ensure_ascii=False,indent=2))
    except (OSError,RuntimeError,ValueError,sqlite3.Error) as e:
        print(json.dumps({"status":"SAFE_ABORT","error_code":type(e).__name__,
                          "private_send_attempts":0,"public_send_attempts":0,
                          "production_changes":0}))
        sys.exit(2)
