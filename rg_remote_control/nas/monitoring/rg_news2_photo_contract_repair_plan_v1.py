#!/usr/bin/env python3
"""NEWS2 photo dispatcher live contract and duplicate guard - READ ONLY.

Evaluates installed source code as AST (never imports/executes it), and reads
status aggregates from immutable SQLite. This script MUST NEVER make bot calls,
start a poller, change Synology schedule, or send/private/public posts.
No article text, photo URL, ID, token, program source or SQL row is printed.
"""
import argparse
import ast
import collections
import json
import pathlib
import re
import sqlite3
import sys
import time

BASE = pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
SOURCE_PATHS = {
    "legacy": "rg_v18.py",
    "outbound": "operator/rg_news2_outbound_queue_v2.py",
    "photo_worker": "telegram_photo_review_flow.py",
    "dsm_tick": "rg_news_dsm_tick.sh",
}
SAFE_STATE = re.compile(r"^[a-z][a-z0-9_]{1,45}$")
FORBIDDEN = ("secret", "token", "password", "chat", "user", "id", "key", "text",
             "caption", "body", "content", "url", "image", "http", "cookie",
             "email", "session", "private", "public", "auth", "credentials")
STATE_BEGIN = ("sent", "send", "pending", "awaiting", "failed", "error", "retry",
               "claimed", "claim", "approved", "rejected", "review", "queued",
               "ready", "dispatch", "card", "uncertain", "photo", "skip", "staged",
               "blocked", "accepted", "accept", "reject", "delivered")
KNOWN_CLI = {"--dry-run","--once","--private-only","--no-public","--max-cards",
             "--limit","--max","--mode","--db","--db-path","--chat-id",
             "--moderator-chat","--force","--replay","--publish","--send",
             "--batch","--status","--diagnose","--selftest"}
FILES = ("rg_v18.py","rg_news2_outbound_queue_v2.py",
         "telegram_photo_review_flow.py","outbound_tick.sh","moderation_tick.sh")
SYMBOLS={"run", "tick", "main", "deliver_one", "claim_one", "handle_callback",
         "init_outbox", "record_sent", "record_uncertain", "send_payload",
         "ArgumentParser", "add_argument", "get_updates", "getUpdates"}
SKIP={"backup","backups","archive","archives","old","venv","cache",
      "secrets","__pycache__","snapshot","snapshots","recovery_v18"}

def clean_state(value):
    if not isinstance(value,str):
        return "unclassified"
    key=value.strip().lower()
    if (not SAFE_STATE.fullmatch(key) or any(x in key for x in FORBIDDEN)
        or not key.startswith(STATE_BEGIN)):
        return "unclassified"
    return key

def db_record(root):
    choices=(root/"news.sqlite3",root/"data/news.sqlite3",root/"db/news.sqlite3",
             root/"state/news.sqlite3")
    p=next((x for x in choices if x.is_file() and not x.is_symlink()),None)
    if p is None:
        return {"found":False}
    report={"found":True,"wal_present":p.with_name(p.name+"-wal").exists(),
            "read_only":True,"tables":{}}
    try:
        db=sqlite3.connect(p.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
        started=time.monotonic()
        db.set_progress_handler(lambda:int(time.monotonic()-started>2),2500)
        try:
            db.execute("PRAGMA query_only=ON")
            existing={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for tab in ("rg_news2_photo_dispatch","moderation_dispatch","rg_v35_photo_audit"):
                if tab not in existing:
                    report["tables"][tab]={"exists":False}
                    continue
                column_names={r[1] for r in db.execute('PRAGMA table_info("'+tab+'")')}
                row={"exists":True,"count":db.execute('SELECT COUNT(*) FROM "'+tab+'"').fetchone()[0],
                     "states":{},"timing_columns":{
                      col:col in column_names for col in ("claimed_at","updated_at","sent_at","attempt_count")}}
                for col in ("state","status","outcome"):
                    if col not in column_names:
                        continue
                    counts=collections.Counter()
                    for v,count in db.execute('SELECT "'+col+'",COUNT(*) FROM "'+tab+'" GROUP BY "'+col+'" LIMIT 80'):
                        counts[clean_state(v)]+=int(count)
                    row["states"][col]=dict(sorted(counts.items()))
                report["tables"][tab]=row
        finally:
            db.close()
    except (sqlite3.Error,OSError,ValueError):
        report["read_error"]=True
    return report

def AST_options(code):
    parsed=ast.parse(code)
    result={"valid_syntax":True,"cli_flags":[],"defined_functions":[],"called_functions":{}}
    flags=set()
    calls=collections.Counter()
    for node in ast.walk(parsed):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in SYMBOLS:
            result["defined_functions"].append(node.name)
        if not isinstance(node,ast.Call):
            continue
        n=node.func
        name=n.id if isinstance(n,ast.Name) else n.attr if isinstance(n,ast.Attribute) else ""
        if name in SYMBOLS:
            calls[name]+=1
        if name=="add_argument":
            for value in node.args:
                if isinstance(value,ast.Constant) and isinstance(value.value,str) and value.value in KNOWN_CLI:
                    flags.add(value.value)
    result["cli_flags"]=sorted(flags)
    result["defined_functions"]=sorted(set(result["defined_functions"]))
    result["called_functions"]=dict(sorted(calls.items()))
    return result

def delivery_guard_ast(tree):
    """Summarize AST guards around calls without returning raw source literals."""
    words=("dry", "run", "limit", "max", "send", "allow", "disable", "enable",
           "private", "moderator", "gate", "retry", "claim", "lock",
           "publish", "review", "photo", "outbox", "pending", "recent",
           "stale", "once", "safe", "duplicate")
    found=[]
    def visit(node, guards, owner):
        local=owner
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            local=node.name if node.name in ("run","main","tick","deliver_one") else "other"
        if isinstance(node,ast.Call):
            target=node.func.id if isinstance(node.func,ast.Name) else (
                node.func.attr if isinstance(node.func,ast.Attribute) else "")
            if target=="deliver_one":
                found.append({"enclosing_function":local,
                              "enclosing_if_count":len(guards),
                              "guard_categories":sorted(set(k for terms in guards for k in terms)),
                              "arg_count":len(node.args),
                              "keyword_arg_count":len(node.keywords)})
        if isinstance(node,ast.If):
            names={x.id.lower() for x in ast.walk(node.test) if isinstance(x,ast.Name)}
            names.update(x.attr.lower() for x in ast.walk(node.test) if isinstance(x,ast.Attribute))
            tags={w for w in words if any(w in name for name in names)}
            visit(node.body,guards+[tags],local)
            visit(node.orelse,guards+[tags],local)
            return
        if isinstance(node,(list,tuple)):
            for child in node:
                if isinstance(child,ast.AST):
                    visit(child,guards,local)
        elif isinstance(node,ast.AST):
            for field in node._fields:
                child=getattr(node,field,None)
                if isinstance(child,(ast.AST,list,tuple)):
                    visit(child,guards,local)
    visit(tree,[],"module")
    return found[:15]

def sources(root):
    results={}
    for label,rel in SOURCE_PATHS.items():
        p=root/rel
        if not p.is_file() or p.is_symlink() or p.stat().st_size>400000:
            results[label]={"found":False}
            continue
        try:
            text=p.read_text(encoding="utf-8",errors="replace")
            d={"found":True,"age_hours":round(max(0,time.time()-p.stat().st_mtime)/3600,1)}
            if rel.endswith(".py"):
                d.update(AST_options(text))
                d["delivery_call_guards"]=delivery_guard_ast(ast.parse(text))
                d["photo_module_reference"]="telegram_photo_review_flow" in text
                d["outbound_module_reference"]="rg_news2_outbound_queue_v2" in text
                d["mentions_getupdates"]="getupdates" in text.lower() or "get_updates" in text.lower()
                d["mentions_channel_send"]="send_message" in text or "sendMessage" in text
            else:
                d["legacy_reference"]="rg_v18.py" in text
                d["outbound_reference"]="rg_news2_outbound_queue_v2" in text
            results[label]=d
        except (SyntaxError,OSError,ValueError):
            results[label]={"found":True,"valid_syntax":False}
    return results

def inspect(root=BASE):
    state=db_record(root)
    code=sources(root)
    photo=state.get("tables",{}).get("rg_news2_photo_dispatch",{})
    statuses=photo.get("states",{}).get("state",{})
    outstanding=sum(v for k,v in statuses.items() if k in
                    ("uncertain","send_uncertain","sending","claimed","pending","queued",
                     "retry","retrying","inflight","processing","unclassified"))
    blockers=[]
    if not state.get("found") or state.get("read_error"):
        blockers.append("LIVE_DB_NOT_VERIFIED")
    if state.get("wal_present"):
        blockers.append("ACTIVE_WAL_NOT_IN_SNAPSHOT")
    if statuses.get("unclassified",0):
        blockers.append("DISPATCH_STATE_AMBIGUOUS")
    if outstanding:
        blockers.append("DISPATCH_MAY_BE_IN_FLIGHT_OR_UNCERTAIN")
    if not code.get("outbound",{}).get("found"):
        blockers.append("OUTBOUND_SOURCE_NOT_VERIFIED")
    if not code.get("photo_worker",{}).get("found"):
        blockers.append("PHOTO_WORKER_NOT_VERIFIED")
    if not code.get("legacy",{}).get("found"):
        blockers.append("LEGACY_SCHEDULER_SOURCE_NOT_VERIFIED")
    # Source presence alone is never enough to prove private destination,
    # idempotent retry semantics, or public-channel exclusion.
    blockers.append("PRIVATE_DELIVERY_IDEMPOTENCE_UNPROVEN")
    return {"schema":"RG_NEWS2_PHOTO_CONTRACT_REPAIR_PLAN_V1",
            "read_only":True,"db_writes":0,"network_calls":0,"telegram_requests":0,
            "applications_started":0,"published_messages":0,
            "dispatch":state,"source_contract":code,"repair_safety":{
                "pending_or_uncertain_possible":outstanding,
                "unattended_scheduler_patch_allowed":False,
                "auto_approval_allowed":False,
                "public_delivery_allowed":False,
                "blockers":sorted(set(blockers)),
                "next_step":"review_source_specific_dispatch_guards_before_a_one_private_card_test"
            }}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        r=pathlib.Path(temp)
        (r/"operator").mkdir()
        (r/"rg_v18.py").write_text("def tick():\n  return 1\n")
        (r/"rg_news_dsm_tick.sh").write_text("python3 rg_v18.py\n")
        (r/"operator/rg_news2_outbound_queue_v2.py").write_text(
          "from telegram_photo_review_flow import deliver_one\n"
          "def run(x):\n  return deliver_one(x,1,2)\n")
        (r/"telegram_photo_review_flow.py").write_text(
          "def deliver_one(db, send, chat):\n  return 'sent'\n")
        cx=sqlite3.connect(str(r/"news.sqlite3"))
        cx.execute("CREATE TABLE rg_news2_photo_dispatch(state text, token text)")
        cx.executemany("INSERT INTO rg_news2_photo_dispatch VALUES(?,?)",[
           ("sending","SECRET_ONE"),("photo_sent","SECRET_TWO"),("unknown_chat_id","SECRET_THREE")])
        cx.commit();cx.close()
        data=inspect(r)
        states=data["dispatch"]["tables"]["rg_news2_photo_dispatch"]["states"]["state"]
        assert states["sending"]==1 and states["photo_sent"]==1 and states["unclassified"]==1
        assert "DISPATCH_STATE_AMBIGUOUS" in data["repair_safety"]["blockers"]
        assert data["source_contract"]["outbound"]["delivery_call_guards"][0]["arg_count"]==3
        assert not data["repair_safety"]["unattended_scheduler_patch_allowed"]
        assert "SECRET" not in json.dumps(data)
    print("RG_NEWS2_PHOTO_CONTRACT_REPAIR_PLAN_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("diagnose","selftest"))
    args=p.parse_args()
    if args.mode=="selftest":
        selftest()
    else:
        print(json.dumps(inspect(),indent=2,sort_keys=True))
