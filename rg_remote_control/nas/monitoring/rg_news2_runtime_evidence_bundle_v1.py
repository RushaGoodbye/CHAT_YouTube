#!/usr/bin/env python3
"""Read-only NAS NEWS2 runtime evidence for diagnosing failed private canary.

No sending, getUpdates, imports of production modules, config-file reads,
token exposure, SQLite mutations, or process restarts. Source AST only.
One invocation emits complete, bounded, redacted evidence needed to patch
the existing private sender. Does not clear any uncertainty/no-retry marker.
"""
import ast
import collections
import datetime
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
FILES={
 "outbound":"operator/rg_news2_outbound_queue_v2.py",
 "photo":"telegram_photo_review_flow.py",
 "callback":"operator/rg_news2_p31_guarded_callback_once.py",
 "rss":"operator/rg_news2_rss_hourly.py",
 "legacy":"rg_v18.py",
 "dsm_tick":"rg_news_dsm_tick.sh"
}
FUNCS={
 "outbound":("run","gates","photo_auto_gate_open","private_send_only",
             "send_one","config","db_connect","maybe_rss_hourly"),
 "photo":("deliver_one","claim_one","send_payload","record_sent",
          "record_uncertain","handle_callback","init_outbox"),
 "callback":("main",),
 "rss":("tick",)
}
EXCEPTIONS={"AssertionError","AttributeError","ConnectionError","FileNotFoundError",
 "ImportError","KeyError","ModuleNotFoundError","OSError","PermissionError",
 "RuntimeError","sqlite3.OperationalError","TypeError","ValueError",
 "TimeoutError","UnboundLocalError","ZeroDivisionError"}
RISK={"send_photo","send_one","send_payload","deliver_one","getUpdates",
      "get_updates","sendMessage","sendPhoto","api","commit","execute",
      "rollback","unlink","unlink_missing_ok","remove","replace",
      "write_text","write_bytes","system","Popen","run","subprocess"}
KEYWORDS=("photo","private","public","send","gate","delivery","moder",
    "capacity","rate","limit","status","state","queue","pilot","budget",
    "auth","allow","disable","enabl","mode","token","path","recipient",
    "chat","callback","worker","rss","config","lock","shadow","review",
    "uncertain","error","reply","retry","silence")
STATE_ALLOW={"awaiting_photo_review","archived_stale","awaiting_moderation",
             "rejected","sent","uncertain_no_automatic_resend","failed",
             "claimed","photo_sent","photo_rejected"}
MAX_AST=50000

def hashed(raw):
    return hashlib.sha256(str(raw).encode("utf-8","replace")).hexdigest()[:12]

def safe_identifier(name):
    return bool(isinstance(name,str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,70}",name))

def symbol(node):
    if isinstance(node,ast.Name):return node.id
    if isinstance(node,ast.Attribute):return node.attr
    return ""

def sanitized_symbols(nodes,limit=35):
    words=set()
    for x in nodes:
        for n in ast.walk(x):
            v=n.id if isinstance(n,ast.Name) else n.attr if isinstance(n,ast.Attribute) else None
            if not safe_identifier(v):continue
            lo=v.lower()
            if any(k in lo for k in KEYWORDS) and not any(x in lo for x in ("password","secret","api_key","bot_token")):
                words.add(v)
    return sorted(words)[:limit]

def calls(nodes):
    cnt=collections.Counter()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n,ast.Call):
                name=symbol(n.func)
                if safe_identifier(name):cnt[name]+=1
    return {name:n for name,n in sorted(cnt.items()) if n>=1 and
            (name in RISK or name in ("gates","photo_auto_gate_open",
               "private_send_only","config","db_connect","claim_one",
               "record_sent","record_uncertain","kyiv_clock","getoff","putoff",
               "reviewed_photo_rate","flock","send_one","maybe_rss_hourly",
               "status","emit","safe","send_photo"))}

def trace_return(node):
    if node is None:return "none"
    if isinstance(node,ast.Constant):
        if node.value is None:return "none"
        if isinstance(node.value,bool):return "boolean"
        if isinstance(node.value,(int,float)):return "number"
        if isinstance(node.value,str):return "string_redacted"
    if isinstance(node,ast.Call):return "call:"+symbol(node.func)
    if isinstance(node,ast.Name):return "name"
    if isinstance(node,ast.Dict):return "dict"
    return type(node).__name__.lower()

def nested_branch(statement):
    data={"kind":type(statement).__name__}
    if isinstance(statement,ast.If):
        data["guard_symbol_hints"]=sanitized_symbols([statement.test],12)
        data["compared_safe_literals"]=sorted({
          n.value for n in ast.walk(statement.test)
          if isinstance(n,ast.Constant) and isinstance(n.value,str)
          and n.value in ("photo","status","once","private","send",
                          "awaiting_photo_review","archived_stale")
        })
        data["body_calls"]=calls(statement.body)
        data["else_calls"]=calls(statement.orelse)
        data["body_returns"]=[trace_return(n.value)
          for sub in statement.body for n in ast.walk(sub) if isinstance(n,ast.Return)][:5]
        data["else_returns"]=[trace_return(n.value)
          for sub in statement.orelse for n in ast.walk(sub) if isinstance(n,ast.Return)][:5]
        data["body_top_level_types"]=[type(n).__name__ for n in statement.body[:20]]
    elif isinstance(statement,ast.Return):
        data["type"]="return"
        data["value_kind"]=trace_return(statement.value)
    elif isinstance(statement,ast.Raise):
        data["type"]="raise"
        data["exception_type"]=symbol(statement.exc.func) if isinstance(statement.exc,ast.Call) else symbol(statement.exc)
    elif isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Call):
        data["top_call"]=symbol(statement.value.func)
    elif isinstance(statement,ast.Assign):
        data["value_kind"]=trace_return(statement.value)
        data["called"]=symbol(statement.value.func) if isinstance(statement.value,ast.Call) else None
    elif isinstance(statement,ast.Try):
        data["body_calls"]=calls(statement.body)
        data["handlers"]=[symbol(h.type) for h in statement.handlers]
    return data

def code_report(root=ROOT):
    out={}
    for key,relative in FILES.items():
        p=root/relative
        meta={"present":p.is_file(),"symlink":p.is_symlink()}
        if not p.is_file() or p.is_symlink() or p.stat().st_size>500000:
            out[key]=meta
            continue
        raw=p.read_bytes()
        meta.update({"bytes":len(raw),"sha12":hashlib.sha256(raw).hexdigest()[:12]})
        if relative.endswith(".sh"):
            meta["legacy_tick_invocation"]=("rg_v18.py" in raw.decode("utf-8","replace"))
            meta["photo_hook_installed"]=("RG_NEWS2_PRIVATE_PHOTO_TICK" in raw.decode("utf-8","replace"))
            out[key]=meta
            continue
        try: t=ast.parse(raw.decode("utf-8","replace"))
        except (SyntaxError,UnicodeError):
            meta["syntax"]="FAIL";out[key]=meta;continue
        meta["syntax"]="PASS"
        meta["imports"]=[]
        for n in t.body:
            if isinstance(n,ast.Import):
                meta["imports"]+= [a.name.split(".")[0] for a in n.names
                        if safe_identifier(a.name.split(".")[0])]
            if isinstance(n,ast.ImportFrom):
                if n.module and safe_identifier(n.module.split(".")[0]):
                    meta["imports"].append(n.module.split(".")[0])
        meta["imports"]=sorted(set(meta["imports"]))[:60]
        meta["main_guard"]=any(isinstance(n,ast.If) and
                          "__main__" in ast.dump(n.test) for n in t.body)
        meta["top_level_calls"]=calls([n for n in t.body
              if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))])
        defs={n.name:n for n in t.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        meta["functions"]={}
        for fn in FUNCS.get(key,()):
            n=defs.get(fn)
            if n is None:continue
            body=n.body
            meta["functions"][fn]={
                "arg_names":[x.arg for x in n.args.posonlyargs+n.args.args if safe_identifier(x.arg)],
                "required_args":len(n.args.posonlyargs+n.args.args)-len(n.args.defaults),
                "call_counts":calls(body),
                "branch_count":sum(isinstance(x,ast.If) for x in ast.walk(n)),
                "return_kinds":[trace_return(x.value) for x in ast.walk(n)
                                  if isinstance(x,ast.Return)][:18],
                "raises":[symbol(x.exc.func) if isinstance(x.exc,ast.Call)
                          else symbol(x.exc) for x in ast.walk(n)
                          if isinstance(x,ast.Raise)][:18],
                "top_statements":[nested_branch(st) for st in body[:32]],
                "all_guard_symbols":sanitized_symbols([x.test for x in ast.walk(n)
                        if isinstance(x,ast.If)],50)
            }
        out[key]=meta
    return out

def db_evidence(root=ROOT):
    db=root/"news.sqlite3"
    if not db.is_file() or db.is_symlink():return {"present":False}
    c=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
    c.execute("PRAGMA query_only=ON")
    data={"present":True,"no_writes":True,"wal_file_present":
          (db.parent/(db.name+"-wal")).exists()}
    try:
        names={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in ("candidates","rg_news2_photo_dispatch","rg_v35_photo_audit",
                     "moderation_dispatch"):
            if name not in names:continue
            fields={x[1] for x in c.execute('PRAGMA table_info("'+name+'")')}
            entry={"rows":c.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]}
            if name=="candidates" and "status" in fields:
                entry["statuses"]={str(value) if str(value) in STATE_ALLOW else
                    "redacted_"+hashed(value):num
                    for value,num in c.execute("SELECT status,COUNT(*) FROM candidates GROUP BY status")}
            if name=="rg_news2_photo_dispatch":
                entry["receipts"]=c.execute(
                    "SELECT COUNT(*) FROM rg_news2_photo_dispatch WHERE telegram_message_id IS NOT NULL"
                ).fetchone()[0] if "telegram_message_id" in fields else None
                if "state" in fields:
                    entry["state_count"]=[{"masked_hash":hashed(value),"n":num}
                      for value,num in c.execute("SELECT state,COUNT(*) FROM rg_news2_photo_dispatch GROUP BY state")]
            data[name]=entry
    finally:c.close()
    return data

def uncertainty(vault=VAULT):
    out={}
    for vers in ("v3","v4","v5","v6"):
        p=vault/("rg_news2_photo_unconfirmed_"+vers+".json")
        val={"exists":p.exists(),"symlink":p.is_symlink()}
        if p.is_file() and not p.is_symlink() and p.stat().st_size<5000:
            try:
                d=json.loads(p.read_text())
                state=d.get("state")
                val["state"]=state if state in (
                    "SEND_ATTEMPTED_REQUIRES_RECEIPT",) else "REDACTED"
            except (ValueError,UnicodeError,OSError):
                val["state"]="UNREADABLE"
        out[vers]=val
    return out

def report(root=ROOT,vault=VAULT):
    return {"schema":"RG_NEWS2_LIVE_RUNTIME_EVIDENCE_BUNDLE_V1",
            "read_only":True,"telegram_api_calls":0,"pollers_started":0,
            "publishes":0,"scheduler_changes":0,"db_mutations":0,
            "source_ast":code_report(root),"sqlite":db_evidence(root),
            "canary_uncertainty_guards":uncertainty(vault),
            "next_step":"Patch confirmed actual source contract, reconcile any uncertain send before another canary."}

def selftest():
    with tempfile.TemporaryDirectory() as td:
        r=pathlib.Path(td)
        (r/"operator").mkdir()
        (r/"rg_news_dsm_tick.sh").write_text("#!/bin/sh\npython3 rg_v18.py tick\n")
        (r/"operator/rg_news2_outbound_queue_v2.py").write_text(
            "secret='SENSITIVE_TOKEN_NEVER_PRINT'\n"
            "def run(mode):\n"
            "    if mode == 'status':\n"
            "        emit('state')\n"
            "    if photo_auto_gate_open():\n"
            "        private_send_only()\n"
            "        deliver_one(db,'NOT_A_REAL_CHAT_ID')\n")
        c=sqlite3.connect(str(r/"news.sqlite3"))
        c.execute("CREATE TABLE candidates(status text)")
        c.execute("INSERT INTO candidates VALUES('awaiting_photo_review')")
        c.execute("CREATE TABLE rg_news2_photo_dispatch(state text,telegram_message_id INT)")
        c.execute("INSERT INTO rg_news2_photo_dispatch VALUES('SENSITIVE_STATE_TOKEN',444)")
        c.commit();c.close()
        result=report(r,r)
        v=result["source_ast"]["outbound"]["functions"]["run"]
        assert v["call_counts"]["deliver_one"]==1
        assert len(v["top_statements"])==2
        assert result["sqlite"]["rg_news2_photo_dispatch"]["receipts"]==1
        d=json.dumps(result)
        assert "SENSITIVE_TOKEN_NEVER_PRINT" not in d
        assert "NOT_A_REAL_CHAT_ID" not in d
        assert "SENSITIVE_STATE_TOKEN" not in d
        assert "444" not in d
        assert "rg_v18.py" not in d or "legacy_tick_invocation" in d
    print("RG_NEWS2_LIVE_RUNTIME_EVIDENCE_BUNDLE_V1_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:
        selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(report(),sort_keys=True,ensure_ascii=False,indent=2))
    else:
        sys.exit("Use selftest or inspect. Inspection never calls Telegram.")
