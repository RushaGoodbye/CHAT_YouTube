#!/usr/bin/env python3
"""NEWS2 photo repair preparation: one safe backup + source-aware status audit.

Never imports installed worker, invokes Telegram, polls, sends, publishes,
changes production database, edits task files, starts processes or enables
public delivery. 'prepare' makes a root-only versioned backup of the four
installed code files and an SQLite online snapshot, so a subsequent strictly
guarded repair can be reverted. 'diagnose' has no writes. No raw SQL row,
caption, URL, identifier, token, source code or shell command is ever printed.
Python 3.8+.
"""
import argparse
import ast
import collections
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import sqlite3
import stat
import sys
import time

BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
BACKUP_PARENT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/backups")
CODE={
    "tick":"rg_news_dsm_tick.sh",
    "legacy":"rg_v18.py",
    "outbound":"operator/rg_news2_outbound_queue_v2.py",
    "photo":"telegram_photo_review_flow.py",
}
VALID=re.compile(r"^[a-z][a-z0-9_]{1,42}$")
SAFE_WORDS=("sent","send","photo","card","accept","reject","review","moder",
            "pending","await","uncertain","retry","claim","queued","queue",
            "failed","fail","block","ready","staged","confirm","dispatch",
            "delivery","delivered","processing","hold","done","complete")
UNSAFE_WORDS=("token","password","secret","chat","user","url","caption",
              "content","text","message_id","email","session","auth","key",
              "credential","cookie","private_chat")
TIMESTAMPS=("claimed_at","updated_at","created_at")
UTC=dt.timezone.utc

def allowed_state(value):
    if not isinstance(value,str):
        return False
    word=value.strip().lower()
    return bool(VALID.fullmatch(word) and
                any(word.startswith(w) for w in SAFE_WORDS) and
                not any(w in word for w in UNSAFE_WORDS))

def get_scripts(root):
    scripts={}
    literals=set()
    for name,rel in CODE.items():
        p=root/rel
        info={"exists":p.is_file() and not p.is_symlink(),"syntax":"unavailable"}
        if not info["exists"] or p.stat().st_size>500000:
            scripts[name]=info
            continue
        try:
            code=p.read_text(encoding="utf-8",errors="replace")
            info["size"]=p.stat().st_size
            info["mtime_age_h"]=round(max(0,time.time()-p.stat().st_mtime)/3600,1)
            info["references_photo"]="telegram_photo_review_flow" in code
            info["references_outbound"]="rg_news2_outbound_queue_v2" in code
            info["references_legacy"]="rg_v18.py" in code
            if rel.endswith(".py"):
                tree=ast.parse(code)
                info["syntax"]="PASS"
                for node in ast.walk(tree):
                    if isinstance(node,ast.Constant) and isinstance(node.value,str) and allowed_state(node.value):
                        literals.add(node.value.lower())
                relevant={"deliver_one","claim_one","record_sent","record_uncertain","run"}
                calls={}
                functions={}
                branches={}
                for node in ast.walk(tree):
                    if isinstance(node,ast.Call):
                        func=node.func
                        n=func.id if isinstance(func,ast.Name) else func.attr if isinstance(func,ast.Attribute) else ""
                        if n in relevant:
                            calls[n]=calls.get(n,0)+1
                    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in relevant:
                        args=node.args
                        functions[node.name]={"required_positional":len(args.posonlyargs)+len(args.args)-len(args.defaults),
                                              "kwonly_count":len(args.kwonlyargs)}
                        branches[node.name]={
                            "if_branches":sum(isinstance(x,ast.If) for x in ast.walk(node)),
                            "loops":sum(isinstance(x,(ast.For,ast.While)) for x in ast.walk(node)),
                            "with_blocks":sum(isinstance(x,(ast.With,ast.AsyncWith)) for x in ast.walk(node)),
                            "exception_handlers":sum(isinstance(x,ast.ExceptHandler) for x in ast.walk(node)),
                        }
                info["selected_calls"]=calls
                info["selected_functions"]=functions
                info["control_flow"]=branches
                info["contains_known_send_rate_cap"]=any(
                    isinstance(x,ast.Constant) and isinstance(x.value,str) and
                    "LIMIT 1" in x.value.upper() for x in ast.walk(tree))
                info["references_telegram_polling"]=any(
                    word in code.lower() for word in ("getupdates","get_updates"))
            else:
                info["syntax"]="NOT_EXECUTED"
        except (OSError,ValueError,UnicodeError,SyntaxError):
            info["syntax"]="INVALID_OR_UNREADABLE"
        scripts[name]=info
    return scripts,literals

def timestamp_age(value,now):
    try:
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            unix=float(value)/1000 if value>1e12 else float(value)
        elif isinstance(value,str) and len(value)<50:
            parsed=dt.datetime.fromisoformat(value.strip().replace("Z","+00:00"))
            if parsed.tzinfo is None:
                return None
            unix=parsed.timestamp()
        else:
            return None
        age=int(now-unix)
        return age if -300<=age<=366*86400 else None
    except (ValueError,OverflowError,TypeError,OSError):
        return None

def outbox_report(db,known):
    out={"db_exists":bool(db),"immutable_snapshot":True,
         "status_counts":{},"row_count":None,
         "state_unknown":None,
         "updated_age_bucket":{},"claimed_age_bucket":{},
         "receipt_column_presence":{},"receipt_nonnull_count":{},
         "wal_may_be_omitted":bool(db and db.with_name(db.name+"-wal").exists())}
    if not db:
        return out
    try:
        conn=sqlite3.connect(db.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
        conn.execute("PRAGMA query_only=ON")
        try:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "rg_news2_photo_dispatch" not in tables:
                out["table_found"]=False
                return out
            out["table_found"]=True
            cols={r[1] for r in conn.execute('PRAGMA table_info("rg_news2_photo_dispatch")')}
            out["row_count"]=conn.execute('SELECT COUNT(*) FROM "rg_news2_photo_dispatch"').fetchone()[0]
            whitelist={x for x in known if allowed_state(x)}
            for col in ("state","status"):
                if col not in cols:continue
                counts=collections.Counter()
                for value,count in conn.execute('SELECT "'+col+'",COUNT(*) FROM "rg_news2_photo_dispatch" GROUP BY "'+col+'" LIMIT 80'):
                    label=value.strip().lower() if isinstance(value,str) else ""
                    if label not in whitelist and not allowed_state(label):
                        label="other_redacted"
                    counts[label]+=int(count)
                out["status_counts"][col]=dict(counts)
                out["state_unknown"]=counts.get("other_redacted",0)
            for col in TIMESTAMPS:
                if col not in cols:
                    continue
                buckets=collections.Counter()
                for (value,) in conn.execute('SELECT "'+col+'" FROM "rg_news2_photo_dispatch" LIMIT 500'):
                    age=timestamp_age(value,time.time())
                    if age is None:buckets["unparsed"]+=1
                    elif age<=600:buckets["under_10m"]+=1
                    elif age<=3600:buckets["under_1h"]+=1
                    elif age<=86400:buckets["under_1d"]+=1
                    else:buckets["over_1d"]+=1
                out[col+"_age_buckets"]=dict(buckets)
            for col in ("telegram_message_id","message_id","photo_message_id",
                        "sent_message_id","receipt_id"):
                if col not in cols:continue
                out["receipt_column_presence"][col]=True
                out["receipt_nonnull_count"][col]=conn.execute(
                    'SELECT COUNT(*) FROM "rg_news2_photo_dispatch" WHERE "'+col+'" IS NOT NULL').fetchone()[0]
        finally:
            conn.close()
    except (sqlite3.Error,OSError,ValueError):
        out["read_error"]=True
    return out

def db_path(root):
    for p in (root/"news.sqlite3",root/"data/news.sqlite3",root/"db/news.sqlite3",
              root/"state/news.sqlite3"):
        if p.is_file() and not p.is_symlink():return p
    return None

def inspect(root=BASE):
    scripts,source_states=get_scripts(root)
    dispatch=outbox_report(db_path(root),source_states)
    states=dispatch.get("status_counts",{}).get("state",{})
    blocked=any(
        k=="other_redacted" or
        any(x in k for x in ("uncertain","sending","inflight","claim","pending","retry"))
        for k,v in states.items() if v)
    return {
        "schema":"RG_NEWS2_PHOTO_REPAIR_BUNDLE_V1","read_only":True,
        "telegram_api_requests":0,"db_writes":0,"publications":0,
        "application_tasks_executed":0,
        "scripts":scripts,"known_photo_dispatch_states":sorted(source_states)[:30],
        "outbox":dispatch,
        "remediation":{
            "live_hook_changed":False,"unattended_apply_enabled":False,
            "active_queue_resend_blocked":blocked,
            "reason":"Private destination and 1-card idempotence not independently verified",
            "public_channel_remains_disabled":True,
            "second_poller_started":False
        }}

def prepare(root=BASE,target_parent=BACKUP_PARENT):
    if os.geteuid()!=0:
        raise RuntimeError("root_required")
    report=inspect(root)
    if not all(report["scripts"][k].get("exists") and
               report["scripts"][k].get("syntax") in ("PASS","NOT_EXECUTED")
               for k in CODE):
        raise RuntimeError("live_script_integrity_gate_failed")
    db=db_path(root)
    if db is None:
        raise RuntimeError("live_database_missing")
    if target_parent.is_symlink():
        raise RuntimeError("backup_symlink_forbidden")
    target_parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(str(target_parent),0o700)
    now=dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest=target_parent/("news2-photo-repair-prep-"+now)
    dest.mkdir(mode=0o700)
    try:
        for key,rel in CODE.items():
            from_file=root/rel
            if from_file.is_symlink():
                raise RuntimeError("source_symlink_forbidden")
            shutil.copyfile(str(from_file),str(dest/(key+".source")))
            os.chmod(str(dest/(key+".source")),0o600)
        # Online backup copies committed data, without reading sensitive rows into output.
        src=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
        dst=sqlite3.connect(str(dest/"news.sqlite3"),timeout=5)
        try:
            src.backup(dst,pages=200,sleep=0.05)
        finally:
            dst.close()
            src.close()
        os.chmod(str(dest/"news.sqlite3"),0o600)
        # Exit safely even if an unresolved dispatch state exists.
        report["backup"]={
            "complete":True,"path":str(dest),
            "scripts_saved":len(CODE),"database_snapshot_saved":True,
            "live_code_mutations":0,"live_db_mutations":0}
        return report
    except Exception:
        # Never leave an incomplete backup mistaken for complete.
        shutil.rmtree(str(dest))
        raise

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        root=pathlib.Path(temp)/"app"
        root.mkdir()
        (root/"operator").mkdir()
        for key,rel in CODE.items():
            p=root/rel
            p.parent.mkdir(parents=True,exist_ok=True)
            if p.suffix==".sh":
                p.write_text("python3 rg_v18.py\n")
            elif key=="outbound":
                p.write_text("from telegram_photo_review_flow import deliver_one\n"+
                             "def run(x):\n  return deliver_one(x,1,2)\n")
            elif key=="photo":
                p.write_text("def deliver_one(x,y,z):\n  state='photo_card_sent'\n  return state\n")
            else:
                p.write_text("def main():\n  return 'awaiting_photo_review'\n")
        conn=sqlite3.connect(str(root/"news.sqlite3"))
        conn.execute("CREATE TABLE rg_news2_photo_dispatch(state text,updated_at int,telegram_message_id int, secret text)")
        conn.execute("INSERT INTO rg_news2_photo_dispatch VALUES('photo_card_sent',1800000000,12345,'PRIVATE_MESSAGE')")
        conn.execute("INSERT INTO rg_news2_photo_dispatch VALUES('send_uncertain',1800000000,NULL,'PRIVATE_MESSAGE')")
        conn.commit();conn.close()
        result=inspect(root)
        assert result["outbox"]["status_counts"]["state"]["photo_card_sent"]==1
        assert result["outbox"]["status_counts"]["state"]["send_uncertain"]==1
        assert result["outbox"]["receipt_nonnull_count"]["telegram_message_id"]==1
        assert result["remediation"]["active_queue_resend_blocked"]
        assert "PRIVATE_MESSAGE" not in json.dumps(result)
        if hasattr(os,"geteuid") and os.geteuid()==0:
            output=prepare(root,pathlib.Path(temp)/"backup")
            assert output["backup"]["complete"]
            assert pathlib.Path(output["backup"]["path"]).joinpath("news.sqlite3").is_file()
            assert conn is not None
    print("RG_NEWS2_PHOTO_REPAIR_BUNDLE_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("selftest","diagnose","prepare"))
    args=p.parse_args()
    if args.mode=="selftest":
        selftest()
    else:
        try:
            output=prepare() if args.mode=="prepare" else inspect()
            print(json.dumps(output,sort_keys=True,ensure_ascii=False,indent=2))
        except (OSError,sqlite3.Error,ValueError,RuntimeError) as e:
            print(json.dumps({"schema":"RG_NEWS2_PHOTO_REPAIR_BUNDLE_V1",
                "status":"SAFE_ABORT","reason_code":str(e)[:100],
                "no_publisher_changes":True,"no_telegram_calls":True}))
            sys.exit(2)
