#!/usr/bin/env python3
"""Read-only RG NEWS2 private route contract. Python 3.8 compatible.

Never import or run the installed sender, never open Telegram connections,
never clear uncertainty, never modify DB or Synology scheduler.
All arbitrary source string literals are omitted.
"""
import ast
import hashlib
import json
import pathlib
import sqlite3
import sys
import tempfile

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
EXPECTED="e94253084ea2"
KNOWN={"status","once","photo","tick","private","dispatch","run","dry-run",
       "test","queue","check"}
CALLS={"gates","photo_auto_gate_open","private_send_only","deliver_one",
       "send_one","maybe_rss_hourly","config","db_connect","api","execute",
       "reviewed_photo_rate","claim_one","record_sent","record_uncertain"}

def name(n):
    if isinstance(n,ast.Name):return n.id
    if isinstance(n,ast.Attribute):return n.attr
    return ""

def details(test):
    vals=sorted({n.value for n in ast.walk(test) if isinstance(n,ast.Constant)
                 and isinstance(n.value,str) and n.value in KNOWN})
    names=sorted({n.id for n in ast.walk(test) if isinstance(n,ast.Name)
                  and n.id in ("mode","enabled","chat","photo_open",
                               "ordinary_open","accepted_waiting","last24",
                               "cooldown","hour","minute")})
    return vals,names

def run_steps(node):
    steps=[]
    for st in node.body:
        if isinstance(st,ast.If):
            vals,ns=details(st.test)
            called=sorted({name(x.func) for branch in (st.body,st.orelse)
                           for n in branch for x in ast.walk(n)
                           if isinstance(x,ast.Call) and name(x.func) in CALLS})
            steps.append({"line":st.lineno,"type":"if","modes":vals,
                          "symbols":ns,"calls":called})
        elif isinstance(st,ast.Try):
            called=sorted({name(x.func) for n in st.body for x in ast.walk(n)
                           if isinstance(x,ast.Call) and name(x.func) in CALLS})
            steps.append({"line":st.lineno,"type":"try","calls":called})
        elif isinstance(st,ast.Expr) and isinstance(st.value,ast.Call):
            n=name(st.value.func)
            if n in CALLS:steps.append({"line":st.lineno,"type":"call","name":n})
        elif isinstance(st,(ast.Assign,ast.AnnAssign)):
            value=st.value
            if isinstance(value,ast.Call) and name(value.func) in CALLS:
                steps.append({"line":st.lineno,"type":"assignment_call",
                              "name":name(value.func)})
    return steps[:50]

def inspect(root=ROOT,vault=VAULT,expected=EXPECTED):
    p=root/"operator/rg_news2_outbound_queue_v2.py"
    if p.is_symlink() or not p.is_file():raise RuntimeError("OUTBOUND_SOURCE_INVALID")
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()[:12]!=expected:
        raise RuntimeError("OUTBOUND_SOURCE_PIN_MISMATCH")
    tree=ast.parse(raw.decode("utf-8"))
    out={"schema":"RG_NEWS2_PRIVATE_ROUTE_CONTRACT_V1","read_only":True,
         "telegram_calls":0,"publications":0,"db_writes":0,
         "source_verified":True,
         "uncertainty_v6_present":(vault/"rg_news2_photo_unconfirmed_v6.json").exists()}
    for fn in ("run","gates","photo_auto_gate_open","private_send_only"):
        found=next((x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==fn),None)
        if not found:continue
        guards=[]
        for x in ast.walk(found):
            if isinstance(x,ast.If):
                vals,ns=details(x.test)
                guards.append({"line":x.lineno,"modes":vals,"symbols":ns,
                               "throws":any(isinstance(k,ast.Raise)
                                   for stmt in x.body for k in ast.walk(stmt))})
        out[fn]={"args":[a.arg for a in found.args.args],
                 "top_steps":run_steps(found),
                 "guards":guards[:40]}
    db=root/"news.sqlite3"
    if db.is_file() and not db.is_symlink():
        c=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
        try:
            out["database"]={
              "pending":c.execute("SELECT count(*) FROM candidates WHERE status=?",
                                  ("awaiting_photo_review",)).fetchone()[0],
              "archived":c.execute("SELECT count(*) FROM candidates WHERE status=?",
                                   ("archived_stale",)).fetchone()[0],
              "receipts":c.execute("SELECT count(*) FROM rg_news2_photo_dispatch WHERE telegram_message_id IS NOT NULL").fetchone()[0]}
        finally:c.close()
    out["safety"]={"regular_send_present":any(
         "send_one" in s.get("calls",[]) for s in out.get("run",{}).get("top_steps",[])),
      "photo_send_present":any(
         "deliver_one" in s.get("calls",[]) for s in out.get("run",{}).get("top_steps",[])),
      "eligible_to_enable_public":False,
      "safe_to_retry_unconfirmed_canary":False}
    return out

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        (root/"operator").mkdir()
        p=root/"operator/rg_news2_outbound_queue_v2.py"
        p.write_text("SECRET='NEVER_EXPOSE'\\n"
          "def run(mode):\\n"
          "    if mode not in ('status','once'): raise RuntimeError('HIDDEN')\\n"
          "    if mode == 'once':\\n"
          "        send_one()\\n"
          "        deliver_one()\\n")
        r=inspect(root,root,hashlib.sha256(p.read_bytes()).hexdigest()[:12])
        text=json.dumps(r)
        assert "status" in text and "once" in text
        assert "send_one" in text and "deliver_one" in text
        assert "NEVER_EXPOSE" not in text and "HIDDEN" not in text
        assert r["telegram_calls"]==0
    print("RG_NEWS2_PRIVATE_ROUTE_CONTRACT_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(inspect(),indent=2,sort_keys=True))
    else:sys.exit("Only selftest or inspect")
