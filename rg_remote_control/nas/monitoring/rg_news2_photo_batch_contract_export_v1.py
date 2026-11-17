#!/usr/bin/env python3
"""Collect ONE redacted source contract needed to fix NEWS2 private photo dispatch.

Static AST, immutable SQLite, zero network and zero writes. No raw strings
other than safe program interface names, and no token, chat ID, URL, candidate
ID, caption, SQL row, Bot API credential or source code is emitted.
"""
import argparse
import ast
import collections
import hashlib
import json
import pathlib
import re
import sqlite3
import sys

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
FILES={
    "active_legacy":"rg_v18.py",
    "private_outbound":"operator/rg_news2_outbound_queue_v2.py",
    "photo_delivery":"telegram_photo_review_flow.py",
    "rss":"operator/rg_news2_rss_hourly.py",
    "callback":"operator/rg_news2_p31_guarded_callback_once.py",
}
FUNCTIONS={"tick","run","main","claim_one","deliver_one","send_payload",
           "record_sent","record_uncertain","validate_photo","handle_callback",
           "init_outbox","inline_keyboard"}
CONTROL=("if","while","for","try","except","with","return","raise","call")
CLI={"status","once","selftest","diagnose","check","private",
     "private-only","dry-run","photo","photo_once","send",
     "--status","--once","--dry-run","--private-only"}
BAD=("password","token","secret","credential","cookie","authorization",
     "privatekey","api_key","chat_id","user_id","message_id","image_url",
     "photo_url","caption","body","content","source_url")
STATUS_PREFIX=("sent","photo","send","uncertain","claim","failed","pending",
               "review","moder","deliv","queue","dispatch","await","ready",
               "retry","block","accept","reject","staged")
SQL_TABLES=("candidates","rg_news2_photo_dispatch",
            "moderation_dispatch","rg_v35_photo_audit")
MAX_ITEMS=180

def safe_symbol(s):
    if not isinstance(s,str) or len(s)>70:
        return None
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,69}",s):
        return None
    if any(w in s.lower() for w in BAD):
        return None
    return s

def caller_name(node):
    if isinstance(node,ast.Name):
        return safe_symbol(node.id)
    if isinstance(node,ast.Attribute):
        return safe_symbol(node.attr)
    return None

def test_tags(test):
    items=set()
    for n in ast.walk(test):
        if isinstance(n,ast.Name):
            items.add(n.id.lower())
        if isinstance(n,ast.Attribute):
            items.add(n.attr.lower())
        if isinstance(n,ast.Constant) and isinstance(n.value,str):
            if n.value.lower() in CLI:
                items.add("MODE:"+n.value.lower())
    whitelist=("pilot","photo","review","moderator","private","public",
               "send","gate","enabled","disabled","card","limit","now",
               "rate","budget","retry","status","state","skip","queue",
               "claim","dry","minute","silence","valid","lock","fresh",
               "callback","complete","origin","allow","deny","schedule")
    result=sorted(set(w for v in items for w in whitelist if w in v))
    result+=sorted(x for x in items if x.startswith("MODE:"))
    return result[:14]

def describe(node):
    if isinstance(node,ast.Call):
        return {"type":"call","target":caller_name(node.func) or "other",
                "args":len(node.args),"kwargs":len(node.keywords)}
    if isinstance(node,ast.If):
        return {"type":"if","guard_tags":test_tags(node.test),
                "body_statements":len(node.body),"else_statements":len(node.orelse)}
    if isinstance(node,ast.Return):
        return {"type":"return","value_is_call":isinstance(node.value,ast.Call)}
    if isinstance(node,ast.Raise):
        return {"type":"raise"}
    if isinstance(node,ast.Try):
        return {"type":"try","handlers":len(node.handlers),
                "body_statements":len(node.body)}
    if isinstance(node,ast.With):
        return {"type":"with"}
    if isinstance(node,(ast.For,ast.While)):
        return {"type":"loop"}
    return {"type":type(node).__name__.lower()}

def source_contract(root):
    out={}
    for kind,relative in FILES.items():
        p=root/relative
        doc={"exists":p.is_file()}
        if not p.is_file() or p.is_symlink():
            out[kind]=doc;continue
        try:
            if p.stat().st_size>1000000:
                doc["error"]="oversized";out[kind]=doc;continue
            code=p.read_text(encoding="utf-8",errors="replace")
            tree=ast.parse(code)
            funcs={}
            for n in tree.body:
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in FUNCTIONS:
                    calls=[]
                    for sub in ast.walk(n):
                        if isinstance(sub,ast.Call):
                            name=caller_name(sub.func)
                            if name and name not in ("int","str","len","bool","list","dict",
                                                    "set","print","isinstance","max","min"):
                                calls.append(name)
                    tree_outline=[]
                    for stmt in n.body[:35]:
                        info=describe(stmt)
                        if isinstance(stmt,ast.Assign) and isinstance(stmt.value,ast.Call):
                            info=describe(stmt.value)
                        if isinstance(stmt,ast.Expr) and isinstance(stmt.value,ast.Call):
                            info=describe(stmt.value)
                        tree_outline.append(info)
                    funcs[n.name]={
                        "argument_names":[x.arg for x in n.args.args if safe_symbol(x.arg)],
                        "required_arguments":len(n.args.args)-len(n.args.defaults),
                        "top_level_outline":tree_outline,
                        "all_called_functions":sorted(set(calls))[:35],
                        "if_branch_count":sum(isinstance(x,ast.If) for x in ast.walk(n))
                    }
            constants={x.value.lower() for x in ast.walk(tree)
                       if isinstance(x,ast.Constant) and isinstance(x.value,str)}
            mode_hints=sorted(constants & CLI)
            state_hints=sorted(x for x in constants
                               if re.fullmatch(r"[a-z][a-z0-9_]{1,50}",x) and
                               x.startswith(STATUS_PREFIX) and
                               not any(w in x for w in BAD))
            doc.update({"syntax":"PASS",
                        "sha12":hashlib.sha256(code.encode()).hexdigest()[:12],
                        "possible_cli_modes":mode_hints,
                        "state_literals":state_hints[:50],
                        "selected_functions":funcs,
                        "main_guard_present":any(isinstance(n,ast.If)
                            and "__main__" in ast.dump(n.test) for n in tree.body),
                        "potential_getupdates":"getupdates" in code.lower(),
                        "potential_public_route":any(w in code.lower()
                            for w in ("public_channel","channel_username","channel_chat")),
                        "known_table_references":sorted(n for n in SQL_TABLES if n in code)})
        except (SyntaxError,ValueError,OSError,UnicodeError):
            doc["syntax"]="FAIL_OR_UNREADABLE"
        out[kind]=doc
    return out

def db_summary(root):
    p=next((p for p in (root/"news.sqlite3",root/"data/news.sqlite3")
            if p.is_file() and not p.is_symlink()),None)
    if p is None:
        return {"found":False}
    result={"found":True,"immutable":True,"photo_dispatch_states":[]}
    cx=sqlite3.connect(p.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
    try:
        cx.execute("PRAGMA query_only=ON")
        tabs={row[0] for row in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "rg_news2_photo_dispatch" not in tabs:
            return result
        cols={r[1] for r in cx.execute("PRAGMA table_info(rg_news2_photo_dispatch)")}
        if "state" in cols:
            for state,n in cx.execute(
                    "SELECT state,COUNT(*) FROM rg_news2_photo_dispatch GROUP BY state LIMIT 60"):
                data=str(state or "")
                label="state_hash_"+hashlib.sha256(data.encode()).hexdigest()[:12]
                result["photo_dispatch_states"].append({
                    "masked_state_hash":label,
                    "state_len":len(data),"rows":int(n),
                    "nonnull_telegram_receipt":None})
            if "telegram_message_id" in cols:
                result["rows_with_telegram_message_id"]=cx.execute(
                    "SELECT COUNT(*) FROM rg_news2_photo_dispatch WHERE telegram_message_id IS NOT NULL"
                ).fetchone()[0]
    finally:
        cx.close()
    return result

def run(root=ROOT):
    return {"schema":"RG_NEWS2_PHOTO_BATCH_CONTRACT_EXPORT_V1",
            "read_only":True,"telegram_calls":0,"db_writes":0,
            "public_posts":0,"pollers_started":0,
            "files":source_contract(root),"db":db_summary(root),
            "note":"No repair invoked. Only known-safe source interface and hashed state signatures shown."}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root=pathlib.Path(d)
        (root/"operator").mkdir()
        (root/"telegram_photo_review_flow.py").write_text(
            "def deliver_one(db, sender, recipient):\n"
            "    token='SECRET_ACCESS_TOKEN_123'\n"
            "    if sender.enabled:\n"
            "        return send_payload(db,recipient)\n"
            "    return None\n")
        cx=sqlite3.connect(str(root/"news.sqlite3"))
        cx.execute("CREATE TABLE rg_news2_photo_dispatch(state text,telegram_message_id int)")
        cx.execute("INSERT INTO rg_news2_photo_dispatch VALUES('a_secret_chat_id_123',1)")
        cx.commit();cx.close()
        result=run(root)
        assert result["files"]["photo_delivery"]["selected_functions"]["deliver_one"]["if_branch_count"]==1
        assert result["db"]["rows_with_telegram_message_id"]==1
        output=json.dumps(result)
        assert "SECRET_ACCESS_TOKEN_123" not in output
        assert "a_secret_chat_id_123" not in output
        assert result["db_writes"]==0 and result["telegram_calls"]==0
    print("RG_NEWS2_PHOTO_BATCH_CONTRACT_EXPORT_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("selftest","diagnose"))
    opt=parser.parse_args()
    if opt.mode=="selftest":selftest()
    else:print(json.dumps(run(),sort_keys=True,ensure_ascii=False,indent=2))
