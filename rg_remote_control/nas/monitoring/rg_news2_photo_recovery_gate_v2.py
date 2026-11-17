#!/usr/bin/env python3
"""NEWS2 photo queue safe-repair decision gate. NO network, process starts or DB writes.

Inspects installed RG scripts via static AST, counts outbox states from an
immutable SQLite snapshot, and reports whether an unattended patch would be safe.
Does not expose raw commands, SQL rows, article text, Telegram identifiers,
credentials, URLs, secrets, or source code. Python 3.8+.
"""
import ast
import argparse
import collections
import json
import pathlib
import re
import sqlite3
import sys

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
EXPECTED={
  "scheduler":"rg_v18.py",
  "queue":"operator/rg_news2_outbound_queue_v2.py",
  "worker":"telegram_photo_review_flow.py",
  "tick":"rg_news_dsm_tick.sh",
}
SAFE_LABEL=re.compile(r"^[a-z][a-z0-9_]{1,50}$")
DISALLOWED=("password","token","key","secret","auth","chat","user",
            "caption","body","content","url","photo","image","text",
            "private","public","session","cookie","id","email")
NAMED={"sent","failed","error","retry","retrying","pending","queued",
       "ready","reserved","claimed","uncertain","send_uncertain",
       "sent_confirmed","delivery_unknown","submitted","delivered",
       "processing","inflight","running","blocked","paused","staged",
       "dispatched","done","confirmed","skipped","rejected","approved",
       "aborted","acknowledged","sending","held","awaiting_review"}
INTEREST={"claim_one","deliver_one","record_sent","record_uncertain",
          "init_outbox","send_payload","handle_callback"}
KNOWN_SCRIPTS={"rg_v18.py","rg_news2_outbound_queue_v2.py",
               "telegram_photo_review_flow.py","rg_news2_rss_hourly.py",
               "outbound_tick.sh","moderation_tick.sh","rg_news_dsm_tick.sh"}

def status_alias(value):
    if not isinstance(value,str):
        return "other_redacted"
    v=value.strip().lower()
    if v in NAMED:
        return v
    if SAFE_LABEL.fullmatch(v) and not any(term in v for term in DISALLOWED):
        if (v.startswith(("sent_","dispatch_","retry_","queued_","pending_",
                          "uncertain_","failed_","awaiting_","ack_"))
            or v.endswith(("_sent","_queued","_uncertain","_pending","_failed"))):
            return v
    return "other_redacted"

def functions(source):
    tree=ast.parse(source)
    data={}
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in INTEREST:
            data[node.name]={"required":len(node.args.posonlyargs)+len(node.args.args)-len(node.args.defaults),
                             "total":len(node.args.posonlyargs)+len(node.args.args)}
    calls=collections.Counter()
    for node in ast.walk(tree):
        if isinstance(node,ast.Call):
            fn=node.func
            name=fn.id if isinstance(fn,ast.Name) else (
                fn.attr if isinstance(fn,ast.Attribute) else None)
            if name in INTEREST:
                calls[name]+=1
    return data,dict(calls)

def code_summary(root,relative):
    file=root/relative
    result={"file":relative,"exists":False}
    if not file.is_file() or file.is_symlink() or file.stat().st_size>=1000000:
        return result
    try:
        data=file.read_text(encoding="utf-8",errors="replace")
        defs,calls=functions(data)
        result.update({"exists":True,"syntax":"PASS","methods_defined":defs,"calls":calls,
                       "imports_worker":"telegram_photo_review_flow" in data,
                       "imports_outbound":"rg_news2_outbound_queue_v2" in data,
                       "contains_getupdates":"getupdates" in data.lower() or "get_updates" in data.lower(),
                       "has_main": '__main__' in data,
                       "references_known_scripts":sorted(n for n in KNOWN_SCRIPTS if n in data)})
    except (SyntaxError,UnicodeError,OSError,ValueError):
        result["syntax"]="UNAVAILABLE"
    return result

def outbox(root):
    db=next((p for p in (root/"news.sqlite3",root/"data/news.sqlite3",
                        root/"db/news.sqlite3",root/"state/news.sqlite3")
             if p.is_file() and not p.is_symlink()),None)
    if db is None:
        return {"found":False,"reason":"unknown_database_path"}
    result={"found":True,"read_only":True,
            "wal_present":db.with_name(db.name+"-wal").exists(),
            "states":{},"rows":{},"has_error":False}
    try:
        connection=sqlite3.connect(db.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
        connection.execute("PRAGMA query_only=ON")
        try:
            names={row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("rg_news2_photo_dispatch","rg_v35_photo_audit",
                          "moderation_dispatch","candidates"):
                if table not in names:
                    result["rows"][table]=None
                    continue
                quoted='"'+table+'"'
                result["rows"][table]=connection.execute(
                    "SELECT COUNT(*) FROM "+quoted).fetchone()[0]
                cols={r[1] for r in connection.execute("PRAGMA table_info("+quoted+")")}
                for col in ("state","status","outcome"):
                    if col not in cols:
                        continue
                    counts=collections.Counter()
                    for val,num in connection.execute(
                        'SELECT "'+col+'",COUNT(*) FROM '+quoted+
                        ' GROUP BY "'+col+'" LIMIT 80'):
                        counts[status_alias(val)]+=int(num)
                    result["states"][table+"."+col]=dict(sorted(counts.items()))
        finally:
            connection.close()
    except (sqlite3.Error,OSError,ValueError):
        result["has_error"]=True
    return result

def main_report(root):
    src={name:code_summary(root,path) for name,path in EXPECTED.items() if name!="tick"}
    tick_path=root/EXPECTED["tick"]
    tick={"exists":tick_path.is_file(),"runs_legacy":False,"mentions_outbound":False}
    if tick["exists"] and not tick_path.is_symlink():
        try:
            s=tick_path.read_text(encoding="utf-8",errors="replace")
            tick["runs_legacy"]="rg_v18.py" in s
            tick["mentions_outbound"]="rg_news2_outbound_queue_v2" in s
        except OSError:
            pass
    db=outbox(root)
    states=db.get("states",{}).get("rg_news2_photo_dispatch.state",{})
    ambiguous=bool(states.get("other_redacted",0))
    unknown_or_uncertain=sum(n for k,n in states.items() if
                             "uncertain" in k or "unknown" in k)
    inferred={
      "legacy_scheduler_without_direct_outbound":bool(
          tick["runs_legacy"] and not tick["mentions_outbound"]),
      "photo_worker_callable_in_outbound":bool(
          src["queue"].get("calls",{}).get("deliver_one",0)),
      "photo_worker_has_required_arguments":src["worker"].get(
          "methods_defined",{}).get("deliver_one"),
      "photo_dispatch_ambiguous_state_count":states.get("other_redacted",0),
      "photo_dispatch_uncertain_state_count":unknown_or_uncertain,
      "safe_to_replay_all_pending":False,
      "safe_to_install_unverified_schedule_hook":False,
      "safe_to_enable_public_delivery":False,
      "next_action":"inspect_dispatch_guard_and_state_machine_before_modifying_scheduler"
    }
    return {"schema":"RG_NEWS2_PHOTO_RECOVERY_GATE_V2","read_only":True,
            "db_writes":0,"network_calls":0,"telegram_poll_calls":0,
            "public_messages_sent":0,"application_workers_executed":0,
            "files":src,"tick":tick,"db":db,"decision":inferred}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        (root/"operator").mkdir()
        (root/"rg_news_dsm_tick.sh").write_text("python3 rg_v18.py\n")
        (root/"rg_v18.py").write_text("def tick():\n  return True\n")
        (root/"operator/rg_news2_outbound_queue_v2.py").write_text(
            "from telegram_photo_review_flow import deliver_one\n"
            "def run(db):\n  return deliver_one(db, 1, 2)\n")
        (root/"telegram_photo_review_flow.py").write_text(
            "def deliver_one(db,send,chat):\n  return 'sent'\n")
        c=sqlite3.connect(str(root/"news.sqlite3"))
        c.execute("CREATE TABLE rg_news2_photo_dispatch(state text, chat_id text)")
        c.execute("INSERT INTO rg_news2_photo_dispatch VALUES('send_uncertain','PRIVATE_CHAT_ID')")
        c.execute("INSERT INTO rg_news2_photo_dispatch VALUES('UNKNOWN_TEXT_SECRET_KEY','PRIVATE_CHAT_ID')")
        c.commit()
        c.close()
        report=main_report(root)
        assert report["db"]["states"]["rg_news2_photo_dispatch.state"]["send_uncertain"]==1
        assert report["db"]["states"]["rg_news2_photo_dispatch.state"]["other_redacted"]==1
        assert report["decision"]["photo_dispatch_uncertain_state_count"]==1
        assert report["decision"]["legacy_scheduler_without_direct_outbound"]
        assert report["decision"]["photo_worker_has_required_arguments"]["required"]==3
        printed=json.dumps(report)
        assert "PRIVATE_CHAT_ID" not in printed
        assert "UNKNOWN_TEXT_SECRET_KEY" not in printed
        assert report["application_workers_executed"]==0
    print("RG_NEWS2_PHOTO_RECOVERY_GATE_V2_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("diagnose","selftest"))
    args=parser.parse_args()
    if args.mode=="selftest":selftest()
    else:print(json.dumps(main_report(ROOT),sort_keys=True,indent=2))
