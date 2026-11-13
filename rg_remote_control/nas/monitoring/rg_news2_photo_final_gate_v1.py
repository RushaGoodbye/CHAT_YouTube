#!/usr/bin/env python3
"""One-pass read-only NEWS2 photo handoff and outbox gate inspection.

Only examines local AST and SQLite aggregates. Never executes application scripts,
sends Telegram requests, starts polling, processes candidates, or writes SQLite.
Raw source, SQL rows, URLs, messages, IDs, tokens and shell commands are never emitted.
Works with Python 3.8 on Synology.
"""
import argparse
import ast
import collections
import datetime
import json
import os
import pathlib
import re
import sqlite3
import sys
import time

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
NAMES=("rg_v18.py","rg_news2_outbound_queue_v2.py",
       "telegram_photo_review_flow.py","rg_news2_rss_hourly.py")
TARGETS={"deliver_one","claim_one","send_payload","handle_callback",
         "init_outbox","main","run","tick","dispatch","record_sent",
         "record_uncertain"}
TABLES=("rg_news2_photo_dispatch","rg_v35_photo_audit","moderation_dispatch")
STATE_FIELDS=("state","status","delivery_state","result","outcome")
SAFE_LABEL=re.compile(r"^[a-z][a-z0-9_]{1,48}$")
DENY=("key","secret","token","pass","chat","id","text","caption","url",
      "email","message","cookie","auth","session","http","private","public")
SAFE_STATES={"pending","ready","queued","sent","sending","delivered","success",
             "failed","error","retry","retried","uncertain","not_sent",
             "held","blocked","rejected","approved","claimed","claiming",
             "inflight","processing","staged","completed","done","unknown",
             "deferred","requeued","reserved","created","manual_review",
             "awaiting_photo_review","awaiting_moderation","photo_reviewed"}
DIR_SKIP={"backup","backups","cache","venv","secrets","archive","archives",
          "snapshots","old","__pycache__","recovery_v18"}

def locate(root,basename):
    picks=[]
    preferred=[root/basename,root/"operator"/basename]
    for p in preferred:
        if p.is_file() and not p.is_symlink():
            return p
    if not root.is_dir() or root.is_symlink():
        return None
    for parent,dirs,files in os.walk(str(root),followlinks=False):
        base=pathlib.Path(parent)
        depth=len(base.relative_to(root).parts)
        dirs[:]=[v for v in dirs if depth<4 and v.lower() not in DIR_SKIP
                 and not v.startswith(".") and not (base/v).is_symlink()]
        if basename in files:
            p=base/basename
            if not p.is_symlink() and p.is_file():
                picks.append(p)
    return picks[0] if len(picks)==1 else None

def expr_name(node):
    if isinstance(node,ast.Name):
        return node.id
    if isinstance(node,ast.Attribute):
        return node.attr
    return None

def AST_file(root,name):
    p=locate(root,name)
    output={"name":name,"found":bool(p)}
    if p is None:
        return output
    try:
        if p.stat().st_size>650000:
            output["reason"]="oversized"
            return output
        code=p.read_text(encoding="utf-8",errors="replace")
        tree=ast.parse(code)
        defs=[]
        calls=collections.Counter()
        guarded=[]
        imports=[]
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in TARGETS:
                defs.append({"name":node.name,
                             "positional_arg_count":len(node.args.posonlyargs)+len(node.args.args),
                             "required_count":len(node.args.posonlyargs)+len(node.args.args)-len(node.args.defaults)})
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                names=[a.name.split(".")[0] for a in node.names] if isinstance(node,ast.Import) else [node.module or ""]
                for part in names:
                    if any(k in part.lower() for k in ("photo","outbound","telegram","news","rg_v18")):
                        if SAFE_LABEL.fullmatch(part.lower()):
                            imports.append(part.lower())
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):
                continue
            n=expr_name(node.func)
            if n in TARGETS:
                calls[n]+=1
            if n in {"run","system","Popen","check_call","check_output","call"}:
                guarded.append(n)
        output.update({
            "syntax":"PASS","bytes":p.stat().st_size,
            "age_hours":round(max(0,time.time()-p.stat().st_mtime)/3600,1),
            "relative_directory_depth":len(p.relative_to(root).parts)-1,
            "entrypoint":any(isinstance(n,ast.If) and "__main__" in ast.dump(n.test)
                            for n in tree.body),
            "selected_functions":defs,"selected_call_counts":dict(calls),
            "imports_of_interest":sorted(set(imports)),
            "possible_process_launch_calls":len(guarded),
            "mentions_photo_worker":("telegram_photo_review_flow" in code),
            "mentions_outbound_module":("rg_news2_outbound_queue_v2" in code),
            "mentions_queue_gate":any(x in code.lower() for x in
                                      ("delivery_gate","auto_delivery","shadow_only","allow_send")),
            "mentions_moderation_chat":any(x in code.lower() for x in
                                           ("moderator_chat","mod_chat","private_chat")),
            "photo_review_statuses":{x:(x in code) for x in
                                     ("awaiting_photo_review","photo_reviewed","awaiting_moderation")}
        })
    except (OSError,ValueError,UnicodeError,SyntaxError):
        output["syntax"]="UNAVAILABLE"
    return output

def table_report(db):
    if db is None:
        return {"found":False}
    out={"found":True,"immutable_read_only":True,
         "wal_present":db.with_name(db.name+"-wal").exists(),
         "tables":{}}
    try:
        cx=sqlite3.connect(db.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
        begin=time.monotonic()
        cx.set_progress_handler(lambda:int(time.monotonic()-begin>4),2500)
        try:
            cx.execute("PRAGMA query_only=ON")
            has={r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in TABLES:
                if table not in has:
                    out["tables"][table]={"found":False}
                    continue
                t='"'+table+'"'
                names={r[1] for r in cx.execute("PRAGMA table_info("+t+")")}
                row={"found":True,"rows":cx.execute("SELECT count(*) FROM "+t).fetchone()[0],
                     "state_groups":{}, "safe_columns_present":{n:(n in names) for n in
                          ("created_at","updated_at","attempts","attempt_count",
                           "last_attempt_at","sent_at","reviewed_at","claimed_at")}}
                for column in STATE_FIELDS:
                    if column not in names:
                        continue
                    q='"'+column+'"'
                    groups=collections.Counter()
                    for value,count in cx.execute("SELECT "+q+", count(*) FROM "+t+
                                                   " GROUP BY "+q+" LIMIT 80"):
                        label=str(value).strip().lower() if value is not None else "null"
                        if label not in SAFE_STATES and (
                            not SAFE_LABEL.fullmatch(label) or any(w in label for w in DENY)):
                            label="other_redacted"
                        groups[label]+=int(count)
                    row["state_groups"][column]=dict(groups)
                out["tables"][table]=row
        finally:
            cx.close()
    except (sqlite3.Error,OSError,ValueError):
        out["error_type"]="unavailable"
    return out

def inspect(root):
    db=next((p for p in (root/"news.sqlite3",root/"data"/"news.sqlite3",
                        root/"db"/"news.sqlite3")
             if p.is_file() and not p.is_symlink()),None)
    script=root/"rg_news_dsm_tick.sh"
    script_report={"found":script.is_file(),"tick_mentions_photo_delivery":False,
                   "tick_mentions_rg_v18":False}
    if script.is_file() and not script.is_symlink() and script.stat().st_size<100000:
        source=script.read_text(encoding="utf-8",errors="replace")
        script_report["tick_mentions_photo_delivery"]=any(
            x in source.lower() for x in ("deliver_one","rg_news2_outbound_queue","photo_review"))
        script_report["tick_mentions_rg_v18"]="rg_v18.py" in source
    return {"schema":"RG_NEWS2_PHOTO_FINAL_GATE_V1","read_only":True,
            "network_calls":0,"app_processes_launched":0,"db_writes":0,
            "telegram_polls":0,"private_messages_sent":0,"public_messages_sent":0,
            "source_inspection":[AST_file(root,x) for x in NAMES],
            "dsm_tick":script_report,"outbox_tables":table_report(db),
            "current_public_delivery_gate_unchanged":True,
            "remediation_executed":False}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        (root/"operator").mkdir()
        (root/"rg_news_dsm_tick.sh").write_text("#!/bin/sh\npython3 rg_v18.py\n")
        (root/"rg_v18.py").write_text("import os\nfrom news import tick\n"+
                                     "def main():\n  return tick()\n")
        (root/"operator/rg_news2_outbound_queue_v2.py").write_text(
            "from telegram_photo_review_flow import deliver_one\n"+
            "def main(x):\n  return deliver_one(x)\n")
        (root/"telegram_photo_review_flow.py").write_text(
            "def deliver_one(db,client,chat):\n  return 'sent'\n")
        cx=sqlite3.connect(str(root/"news.sqlite3"))
        cx.execute("CREATE TABLE rg_news2_photo_dispatch(state text, token text)")
        cx.execute("INSERT INTO rg_news2_photo_dispatch VALUES('uncertain','hidden')")
        cx.commit();cx.close()
        result=inspect(root)
        assert result["dsm_tick"]["tick_mentions_rg_v18"]
        assert result["outbox_tables"]["tables"]["rg_news2_photo_dispatch"]["state_groups"]["state"]["uncertain"]==1
        assert result["source_inspection"][1]["selected_call_counts"]["deliver_one"]==1
        assert "hidden" not in json.dumps(result)
        assert result["app_processes_launched"]==0 and result["db_writes"]==0
    print("RG_NEWS2_PHOTO_FINAL_GATE_SELFTEST_PASS")

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("mode",choices=("selftest","diagnose"))
    o=cli.parse_args()
    if o.mode=="selftest":
        selftest()
    else:
        print(json.dumps(inspect(ROOT),sort_keys=True,indent=2))
