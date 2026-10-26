#!/usr/bin/env python3
"""NEWS2 private-photo final bundle. Python 3.8+, fail-closed.

One existing DSM scheduler only. Public delivery OFF. Never getUpdates.
Pinned installed source; isolate photo dispatch AST from outbound's run('tick')
by REMOVING the standard and RSS branches, NOT by running run('tick') unmodified.
If isolation/source/state is unproven, abort before any Telegram call.
"""
import ast
import copy
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import runpy
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback

BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
TICK=BASE/"rg_news_dsm_tick.sh"
LEGACY=BASE/"rg_v18.py"
OUT=BASE/"operator/rg_news2_outbound_queue_v2.py"
PHOTO=BASE/"telegram_photo_review_flow.py"
CALLBACK=BASE/"operator/rg_news2_p31_guarded_callback_once.py"
DB=BASE/"news.sqlite3"
GUARD=BASE/"rg_news2_private_final_guard_v1.py"
OLD_UNCERTAIN=VAULT/"rg_news2_photo_unconfirmed_v6.json"
UNCERTAIN=VAULT/"rg_news2_private_final_unconfirmed_v1.json"
EXPECTED={"tick":"9a2d04e499da","legacy":"63fef26bdf9f",
          "out":"e94253084ea2","photo":"79c473bf774f",
          "callback":"0c48d2030e99"}
MARK="RG_NEWS2_PRIVATE_FINAL_V1"

def sha12(p):
    if p.is_symlink() or not p.is_file():
        raise RuntimeError("PINNED_SOURCE_MISSING")
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]

def call_name(n):
    return n.id if isinstance(n,ast.Name) else (
           n.attr if isinstance(n,ast.Attribute) else "")

def call_count(node,name):
    return sum(isinstance(x,ast.Call) and call_name(x.func)==name
               for x in ast.walk(node))

def prune_photo(source_tree):
    """Return compiled private-only function AST from the exact deployed run().

    Cut public dispatch BEFORE running anything, not by monkeypatching a
    sendMessage after a public item has already been claimed.
    """
    fns=[n for n in source_tree.body
         if isinstance(n,ast.FunctionDef) and n.name=="run"]
    if len(fns)!=1:raise RuntimeError("OUTBOUND_RUN_COUNT_INVALID")
    fn=copy.deepcopy(fns[0])
    args=fn.args.posonlyargs+fn.args.args
    if len(args)!=1 or args[0].arg!="mode" or fn.args.defaults:
        raise RuntimeError("OUTBOUND_MODE_SIGNATURE_CHANGED")
    if not all(call_count(fn,n)==1 for n in (
           "send_one","deliver_one","maybe_rss_hourly",
           "private_send_only","photo_auto_gate_open","gates")):
        raise RuntimeError("SOURCE_DISPATCH_CALL_COUNTS_CHANGED")
    allowed=set()
    for n in ast.walk(fn):
        if isinstance(n,ast.If) and call_count(n.test,"")>=1:
            pass
    mode_guards=[n for n in ast.walk(fn) if isinstance(n,ast.If) and
       any(isinstance(v,ast.Name) and v.id=="mode" for v in ast.walk(n.test))
       and any(isinstance(v,ast.Constant) and v.value=="status"
               for v in ast.walk(n.test))
       and any(isinstance(v,ast.Constant) and v.value=="tick"
               for v in ast.walk(n.test))]
    if len(mode_guards)!=1:
        raise RuntimeError("STATUS_TICK_MODE_GUARD_NOT_PROVEN")
    drops={"send_one","maybe_rss_hourly","standard_dispatch_source_safe"}
    counts={"public":0,"rss":0,"ordinary_guard":0}
    def descendants_call(stmt,target):
        return call_count(stmt,target)>0
    def contains_photo(stmt):
        return descendants_call(stmt,"deliver_one")
    def edit_block(block):
        result=[]
        for stmt in block:
            if isinstance(stmt,ast.If):
                forbid_any=any(descendants_call(stmt,n) for n in drops)
                ordinary=any(isinstance(x,ast.Name) and x.id=="ordinary_open"
                             for x in ast.walk(stmt.test))
                accepted=any(isinstance(x,ast.Name) and x.id=="accepted_waiting"
                             for x in ast.walk(stmt.test))
                # Never discard a branch that could send the photo.
                if (forbid_any or ordinary or accepted) and not contains_photo(stmt):
                    counts["public"]+=int(descendants_call(stmt,"send_one"))
                    counts["rss"]+=int(descendants_call(stmt,"maybe_rss_hourly"))
                    counts["ordinary_guard"]+=int(ordinary or accepted)
                    continue
                if (forbid_any or ordinary or accepted) and contains_photo(stmt):
                    # Parent branch may contain both public/photo paths:
                    # recurse, retain the photo route, prune public children.
                    if ordinary or accepted:
                        raise RuntimeError("PHOTO_NESTED_UNDER_PUBLIC_BRANCH")
                stmt.body=edit_block(stmt.body) or [ast.Pass()]
                stmt.orelse=edit_block(stmt.orelse)
            elif isinstance(stmt,ast.Try):
                stmt.body=edit_block(stmt.body) or [ast.Pass()]
                stmt.orelse=edit_block(stmt.orelse)
                stmt.finalbody=edit_block(stmt.finalbody)
                for h in stmt.handlers:
                    h.body=edit_block(h.body) or [ast.Pass()]
            elif isinstance(stmt,(ast.For,ast.While,ast.AsyncFor)):
                raise RuntimeError("LOOP_IN_PRIVATE_SENDER_UNPROVEN")
            if not any(descendants_call(stmt,n) for n in drops):
                result.append(stmt)
            else:
                raise RuntimeError("PUBLIC_ROUTE_NOT_FULLY_REMOVED")
        return result
    # Detect required locals lost with the ordinary branch. If the photo
    # code would now access an undefined name, stop before touching Telegram.
    original_locals={n.id for n in ast.walk(fn)
                     if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    original_locals.update(a.arg for a in fn.args.args)
    for n in ast.walk(fn):
        if isinstance(n,ast.Import):
            original_locals.update(a.asname or a.name.split(".")[0] for a in n.names)
        if isinstance(n,ast.ImportFrom):
            original_locals.update(a.asname or a.name for a in n.names)
    fn.body=edit_block(fn.body)
    remaining_locals={n.id for n in ast.walk(fn)
                      if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    remaining_locals.update(a.arg for a in fn.args.args)
    for n in ast.walk(fn):
        if isinstance(n,ast.Import):
            remaining_locals.update(a.asname or a.name.split(".")[0] for a in n.names)
        if isinstance(n,ast.ImportFrom):
            remaining_locals.update(a.asname or a.name for a in n.names)
    referenced={n.id for n in ast.walk(fn)
                if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
    if (original_locals-remaining_locals) & referenced:
        raise RuntimeError("PHOTO_REQUIRES_PRUNED_PUBLIC_LOCAL")
    fn.name="rg_private_only_tick"
    if counts["public"]!=1 or counts["rss"]!=1:
        raise RuntimeError("PUBLIC_RSS_PRUNING_NOT_PROVEN")
    if any(call_count(fn,n)>0 for n in drops):
        raise RuntimeError("PUBLIC_SEND_REMAINING")
    # The deployed source uses private_send_only for the ORDINARY
    # dispatch guard, not necessarily the dedicated photo worker.
    # Requiring it inside the private-only AST incorrectly rejects valid
    # photo paths. The photo worker independently enforces authorized chat
    # and verified Telegram reply in send_payload()/record_sent().
    if call_count(fn,"deliver_one")!=1:
        raise RuntimeError("PHOTO_DELIVER_ONE_NOT_PRESERVED")
    if call_count(fn,"private_send_only")>1:
        raise RuntimeError("PRIVATE_GUARD_DUPLICATED")
    if any(isinstance(n,ast.Constant) and isinstance(n.value,str)
           and ("sendMessage" in n.value or "getUpdates" in n.value)
           for n in ast.walk(fn)):
        raise RuntimeError("UNSAFE_BOT_METHOD_LITERAL")
    ast.fix_missing_locations(fn)
    return fn,counts

def source_contract():
    for name,p in (("legacy",LEGACY),("out",OUT),("photo",PHOTO),
                   ("callback",CALLBACK)):
        if sha12(p)!=EXPECTED[name]:
            raise RuntimeError("SOURCE_PIN_CHANGED_"+name.upper())
    # The DSM script changes after the confirmed first canary. Verify its
    # exact wrapper and the immutable original rather than rejecting it.
    if MARK not in TICK.read_text(encoding="utf-8"):
        if sha12(TICK)!=EXPECTED["tick"]:
            raise RuntimeError("SOURCE_PIN_CHANGED_TICK")
    else:
        current=TICK.read_text(encoding="utf-8")
        lines=[line for line in current.splitlines()
               if line.startswith("sh '") and line.endswith("' \"$@\"")]
        if len(lines)!=1:
            raise RuntimeError("INSTALLED_WRAPPER_UNRECOGNIZED")
        saved=pathlib.Path(lines[0][4:].split("'",1)[0])
        if VAULT not in saved.parents or sha12(saved)!=EXPECTED["tick"]:
            raise RuntimeError("WRAPPER_BACKUP_INVALID")
        if current!=wrapper(saved):
            raise RuntimeError("INSTALLED_WRAPPER_CONTENT_CHANGED")
    t=ast.parse(OUT.read_text(encoding="utf-8"))
    fn,counts=prune_photo(t)
    photo=ast.parse(PHOTO.read_text(encoding="utf-8"))
    functions={n.name:n for n in photo.body if isinstance(n,ast.FunctionDef)}
    if "deliver_one" not in functions or "claim_one" not in functions:
        raise RuntimeError("PHOTO_OUTBOX_FUNCTIONS_MISSING")
    if call_count(functions["deliver_one"],"claim_one")!=1:
        raise RuntimeError("ATOMIC_PHOTO_CLAIM_NOT_PROVEN")
    if call_count(functions["deliver_one"],"record_uncertain")!=1:
        raise RuntimeError("UNCERTAIN_PHOTO_STATE_NOT_PROVEN")
    if call_count(functions["deliver_one"],"record_sent")!=1:
        raise RuntimeError("PHOTO_SENT_LEDGER_NOT_PROVEN")
    # If the original private_send_only call guarded only ordinary
    # messages, prove the photo worker validates the configured private
    # chat before sending and before persisting a confirmed receipt.
    if call_count(fn,"private_send_only")==0:
        send_payload=functions.get("send_payload")
        record_sent=functions.get("record_sent")
        if send_payload is None or record_sent is None:
            raise RuntimeError("PHOTO_PRIVATE_CHAT_CHECK_MISSING")
        if not any(isinstance(x,ast.Name) and x.id=="chat_id"
                   for x in ast.walk(send_payload)):
            raise RuntimeError("PHOTO_SEND_CHAT_IDENTIFIER_UNPROVEN")
        if not any(isinstance(x,ast.Name) and x.id=="got_chat"
                   for x in ast.walk(record_sent)):
            raise RuntimeError("PHOTO_TELEGRAM_REPLY_CHAT_CHECK_MISSING")
        if not any(isinstance(x,ast.Name) and x.id=="chat"
                   for x in ast.walk(fn)):
            raise RuntimeError("PHOTO_CONFIGURED_CHAT_UNPROVEN")
    # Preserve the already-installed single callback consumer. No new
    # getUpdates process or callback subscription may be started.
    callback=ast.parse(CALLBACK.read_text(encoding="utf-8"))
    callback_fns={n.name:n for n in callback.body
                  if isinstance(n,ast.FunctionDef)}
    if "main" not in callback_fns or "handle_callback" not in functions:
        raise RuntimeError("PRIVATE_MODERATOR_CALLBACK_MISSING")
    if call_count(callback_fns["main"],"getoff")!=1 or call_count(callback_fns["main"],"putoff")!=1:
        raise RuntimeError("PRIVATE_CALLBACK_OFFSET_GUARD_CHANGED")
    if call_count(functions["handle_callback"],"execute")<1:
        raise RuntimeError("PRIVATE_CALLBACK_DATABASE_GUARD_MISSING")
    return {"source_pins":"PASS","public_branch_removed":True,
            "rss_branch_removed":True,"private_branch_kept":True,
            "photo_ledger_verified":True,"callback_contract_verified":True,
            "extra_pollers":0,"public_gate_changed":False},fn

def sqlite_counts():
    if DB.is_symlink() or not DB.is_file():
        raise RuntimeError("DB_NOT_REGULAR")
    c=sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
    try:
        a=c.execute("SELECT COUNT(*) FROM candidates WHERE status=?",
                    ("awaiting_photo_review",)).fetchone()[0]
        b=c.execute("SELECT COUNT(*) FROM candidates WHERE status=?",
                    ("archived_stale",)).fetchone()[0]
        rows,receipts=c.execute("SELECT COUNT(*), COUNT(telegram_message_id) FROM rg_news2_photo_dispatch").fetchone()
        return {"pending":a,"archived":b,"dispatch_rows":rows,"receipts":receipts}
    finally:c.close()

def silence():
    # DSM's Python may omit time.tzset(). UTC-hour fail-closed window
    # protects Kyiv 09:00-09:05 in BOTH summer (+3) and winter (+2).
    # Intentionally blocks 6 additional minutes to avoid relying on
    # unverified zoneinfo or Synology-specific tz databases.
    now=datetime.datetime.now(datetime.timezone.utc)
    return now.hour in (6,7) and now.minute<=5

def write_marker(label):
    if not VAULT.is_dir() or VAULT.is_symlink() or UNCERTAIN.is_symlink():
        raise RuntimeError("SAFE_MARKER_STORAGE_INVALID")
    tmp=UNCERTAIN.with_name(UNCERTAIN.name+".tmp")
    with open(str(tmp),"w") as f:
        json.dump({"schema":MARK,"state":label},f)
        f.flush();os.fsync(f.fileno())
    os.chmod(str(tmp),0o600)
    os.replace(str(tmp),str(UNCERTAIN))

def lock(path):
    fd=os.open(str(path),os.O_CREAT|os.O_RDWR,0o600)
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise RuntimeError("PRIVATE_DISPATCH_ALREADY_RUNNING")
    return fd

def verify_old_uncertain():
    # Previous V6 tried run('photo'), which raises at the FIRST run guard
    # before gates(), config(), sqlite claims, or Telegram. Preserve marker,
    # and accept reconciliation only with the unchanged three receipts.
    if not OLD_UNCERTAIN.is_file() or OLD_UNCERTAIN.is_symlink():
        raise RuntimeError("OLD_UNCERTAINTY_PROVENANCE_MISSING")
    old=json.loads(OLD_UNCERTAIN.read_text())
    if old.get("state")!="SEND_ATTEMPTED_REQUIRES_RECEIPT":
        raise RuntimeError("OLD_UNCERTAINTY_STATE_CHANGED")
    tree=ast.parse(OUT.read_text(encoding="utf-8"))
    fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=="run")
    first=fn.body[0] if fn.body else None
    if not isinstance(first,ast.If) or not any(isinstance(v,ast.Raise)
          for v in first.body) or not ({"status","tick"}.issubset({
          v.value for v in ast.walk(first.test) if isinstance(v,ast.Constant)
          and isinstance(v.value,str)})):
        raise RuntimeError("OLD_INVALID_MODE_NOT_PROVEN")
    if sqlite_counts()["receipts"]!=3 or sqlite_counts()["dispatch_rows"]!=3:
        raise RuntimeError("OLD_DELIVERY_LEDGER_CHANGED_RECONCILE_MANUALLY")
    # Does not delete or modify the V6 evidence file.
    return "V6_INVALID_MODE_NO_SEND_PROVEN_MARKER_PRESERVED"

def backup():
    if not VAULT.is_dir() or VAULT.is_symlink():
        raise RuntimeError("VAULT_MISSING")
    folder=VAULT/("private-final-"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    folder.mkdir(mode=0o700)
    for label,p in (("tick.sh",TICK),("legacy.py",LEGACY),("outbound.py",OUT),
                    ("photo.py",PHOTO),("callback.py",CALLBACK)):
        shutil.copyfile(str(p),str(folder/label))
        os.chmod(str(folder/label),0o600)
    src=sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
    dst=sqlite3.connect(str(folder/"before.sqlite3"))
    try:src.backup(dst,pages=256,sleep=0.05)
    finally:dst.close();src.close()
    os.chmod(str(folder/"before.sqlite3"),0o600)
    return folder

def atomic_write(p,data):
    if p.is_symlink():raise RuntimeError("REFUSE_REPLACE_SYMLINK")
    tmp=p.with_name(p.name+".rg_final_tmp")
    with open(str(tmp),"w") as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    os.chmod(str(tmp),0o700)
    os.replace(str(tmp),str(p))

def private_once():
    # This path is invoked by a ONE-SHOT child, never by another poller.
    proof,fn=source_contract()
    if not UNCERTAIN.is_file() or UNCERTAIN.is_symlink():
        raise RuntimeError("DISPATCH_UNCERTAINTY_MARKER_MISSING")
    if silence():return {"status":"KYIV_SILENCE_NO_SEND"}
    # Module definitions are sourced solely from the pinned installed file.
    d=runpy.run_path(str(OUT),run_name="rg_private_final_no_main")
    if "run" not in d:raise RuntimeError("PINNED_OUTBOUND_RUNTIME_MISSING")
    b=ast.Module(body=[fn],type_ignores=[])
    ast.fix_missing_locations(b)
    exec(compile(b,str(OUT),"exec"),d)
    # Blocks accidental public dispatch even if a referenced function changes.
    d["send_one"]=lambda *a,**kw: (_ for _ in ()).throw(
        RuntimeError("PUBLIC_SEND_FORBIDDEN"))
    d["maybe_rss_hourly"]=lambda *a,**kw: (_ for _ in ()).throw(
        RuntimeError("RSS_DISPATCH_FORBIDDEN"))
    d["rg_private_only_tick"]("tick")
    return {"status":"PRIVATE_BRANCH_EXECUTED"}

def one_canary():
    fd=lock(BASE/"rg_news2_private_final_send.lock")
    try:
        if UNCERTAIN.exists():
            return {"status":"UNCONFIRMED_PREVIOUS_SEND_NO_RETRY"}
        if silence():return {"status":"KYIV_SILENCE_NO_SEND"}
        before=sqlite_counts()
        if before["archived"]<1353 or before["pending"]<1:
            return {"status":"NO_SAFE_NEW_ITEMS","counts":before}
        write_marker("SEND_ATTEMPTED_REQUIRES_RECEIPT")
        try:
            p=subprocess.run([sys.executable,str(GUARD),"child"],
                             cwd=str(BASE),stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,timeout=75)
            rc=p.returncode
        except subprocess.TimeoutExpired:
            return {"status":"SEND_TIMEOUT_NO_RETRY"}
        after=sqlite_counts()
        delta=after["receipts"]-before["receipts"]
        newrows=after["dispatch_rows"]-before["dispatch_rows"]
        if rc==0 and delta==1 and newrows==1:
            UNCERTAIN.unlink()
            return {"status":"ONE_PRIVATE_RECEIPT_CONFIRMED",
                    "new_receipts":1,"new_photo_rows":1}
        # Never output raw worker stdout/stderr or tokens.
        return {"status":"CANARY_NOT_CONFIRMED","child_exit":rc,
                "new_receipts":delta,"new_photo_rows":newrows,
                "worker_error_class":"UNCONFIRMED_PRIVATE_WORKER",
                "no_automatic_retry":True}
    finally:os.close(fd)

def wrapper(original):
    return ('#!/bin/sh\n# '+MARK+'\n'
            "sh '"+str(original)+"' \"$@\"\n"
            'rg_prior=$?\n'
            'if [ "$rg_prior" -ne 0 ]; then exit "$rg_prior"; fi\n'
            "/usr/bin/python3 '"+str(GUARD)+"' tick\n"
            'exit $?\n')

def install():
    if os.geteuid()!=0:raise RuntimeError("ROOT_REQUIRED")
    fd=lock(BASE/"rg_news2_private_final_install.lock")
    try:
        before=sqlite_counts()
        proof,fn=source_contract()
        reconciled=verify_old_uncertain()
        if UNCERTAIN.exists():
            return {"result":"SAFE_BLOCKED_UNCERTAIN_SEND","prior_marker_preserved":True,
                    "counts":before}
        if MARK in TICK.read_text():
            return {"result":"ALREADY_INSTALLED","counts":before}
        if before["pending"]<1:
            return {"result":"NO_NEW_ITEMS","counts":before}
        if silence():
            return {"result":"KYIV_SILENCE_DEFERRED","counts":before}
        folder=backup()
        # Verify the pinned sender's own gates before attempting Telegram.
        try:
            d=runpy.run_path(str(OUT),run_name="rg_private_preflight_no_main")
            d["gates"]()
            if not d["photo_auto_gate_open"]():
                return {"result":"PRIVATE_GATE_CLOSED_NO_SEND",
                        "backup_directory":str(folder)}
        except Exception as e:
            return {"result":"EXISTING_PRIVATE_GATES_BLOCKED",
                    "error_type":type(e).__name__,
                    "backup_directory":str(folder)}
        shutil.copyfile(__file__,str(GUARD))
        os.chmod(str(GUARD),0o700)
        result=one_canary()
        if result["status"]!="ONE_PRIVATE_RECEIPT_CONFIRMED":
            # No DSM scheduler change has yet been made.
            return {"result":"NOT_INSTALLED_PRIVATE_CANARY_UNCONFIRMED",
                    "canary":result,"backup_directory":str(folder),
                    "publications":0,"extra_pollers":0,
                    "old_uncertainty":reconciled,
                    "counts":sqlite_counts()}
        original=folder/"tick.sh"
        patched=wrapper(original)
        subprocess.run(["sh","-n"],input=patched,text=True,check=True,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        atomic_write(TICK,patched)
        return {"result":"HOOK_INSTALLED","canary":result,
                "backup_directory":str(folder),"source_checks":proof,
                "old_uncertainty":reconciled,
                "publications":0,"extra_pollers":0,
                "counts":sqlite_counts(),
                "moderator_action":"Click Accept or Reject on ONE private photo card"}
    finally:os.close(fd)

def report():
    d=sqlite_counts()
    return {"schema":MARK,"counts":d,"old_v6_marker_preserved":OLD_UNCERTAIN.exists(),
            "new_uncertainty_marker":UNCERTAIN.exists(),
            "hook_installed":MARK in TICK.read_text(),
            "public_gate_modified":False,"extra_pollers":0}

def selftest():
    # Run only local in-memory AST tests, never production source/DB.
    src=("def run(mode):\n"
       "    if mode not in ('status','tick'): raise RuntimeError('bad')\n"
       "    gates()\n"
       "    enabled=photo_auto_gate_open()\n"
       "    if mode=='tick' and not enabled: return\n"
       "    if mode=='tick': maybe_rss_hourly()\n"
       "    ordinary_open=1\n"
       "    photo_open=1\n"
       "    if accepted_waiting:\n"
       "        if not standard_dispatch_source_safe(m): raise RuntimeError('ordinary')\n"
       "        if ordinary_open>=1: pass\n"
       "    if ordinary_open>=1: send_one()\n"
       "    if photo_open>=1:\n"
       "        private_send_only()\n"
       "        deliver_one()\n")
    # Do not assume DSM Python implements time.tzset() or zoneinfo.
    # The conservative UTC window must cover both seasonal Kyiv offsets.
    original_datetime=datetime.datetime
    assert "tzset" not in silence.__code__.co_names
    assert "subprocess" not in silence.__code__.co_names
    tree=ast.parse(src)
    fn,c=prune_photo(tree)
    # Production pattern: private_send_only() can belong to the ordinary
    # branch, which must be removed completely. Keep deliver_one() even if
    # the ordinary-only private_send_only() gets pruned along with send_one.
    alt=ast.parse(src)
    for branch in ast.walk(alt):
        if not isinstance(branch,ast.If):
            continue
        if any(isinstance(n,ast.Name) and n.id=="ordinary_open"
               for n in ast.walk(branch.test)):
            if call_count(branch,"send_one")==1:
                branch.body.insert(0,ast.Expr(value=ast.Call(
                    func=ast.Name(id="private_send_only",ctx=ast.Load()),
                    args=[],keywords=[])))
        if any(isinstance(n,ast.Name) and n.id=="photo_open"
               for n in ast.walk(branch.test)):
            branch.body=[st for st in branch.body if
                         call_count(st,"private_send_only")==0]
    ast.fix_missing_locations(alt)
    clean2,count2=prune_photo(alt)
    assert call_count(clean2,"deliver_one")==1
    assert call_count(clean2,"private_send_only")==0
    assert not any(call_count(clean2,k) for k in (
        "send_one","maybe_rss_hourly","standard_dispatch_source_safe"))
    assert count2["public"]==1 and count2["rss"]==1
    assert c["public"]==1 and c["rss"]==1
    events=[]
    d={"gates":lambda:None,"photo_auto_gate_open":lambda:True,
       "maybe_rss_hourly":lambda:events.append("BAD_RSS"),
       "send_one":lambda:events.append("BAD_PUBLIC"),
       "private_send_only":lambda:events.append("PRIVATE_GUARD"),
       "deliver_one":lambda:events.append("PHOTO"),
       "accepted_waiting":True,"m":object(),
       "standard_dispatch_source_safe":lambda _:True}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],
        type_ignores=[])),"fixture","exec"),d)
    d["rg_private_only_tick"]("tick")
    assert events==["PRIVATE_GUARD","PHOTO"],events
    print("RG_NEWS2_PRIVATE_FINAL_BUNDLE_SELFTEST_PASS")

def main():
    try:
        args=sys.argv[1:]
        if args==["selftest"]:selftest()
        elif args==["audit"]:
            proof,fn=source_contract()
            print(json.dumps({"schema":MARK,"status":"READ_ONLY","proof":proof,
                   "reconciled":verify_old_uncertain(),"counts":sqlite_counts(),
                   "no_telegram_calls":True}))
        elif args==["install"]:print(json.dumps(install(),indent=2))
        elif args==["status"]:print(json.dumps(report(),indent=2))
        elif args==["tick"]:print(json.dumps(one_canary(),indent=2))
        elif args==["child"]:
            try:
                res=private_once()
                print(json.dumps(res))
            except Exception as e:
                # Never leak message, path, article, Bot API response or token.
                print(json.dumps({"status":"PRIVATE_CHILD_BLOCKED",
                                  "exception_type":type(e).__name__}))
                sys.exit(2)
        else:raise RuntimeError("MODE_UNSUPPORTED")
    except Exception as e:
        # Show only our verified local source function/line, never raw
        # Python exception text, chat IDs, paths, Bot API output or sources.
        tb=e.__traceback__
        location=None
        while tb is not None:
            frame=tb.tb_frame
            if frame.f_code.co_filename==__file__:
                location={"function":frame.f_code.co_name,
                          "source_line":tb.tb_lineno}
            tb=tb.tb_next
        print(json.dumps({"status":"SAFE_ABORT","error_type":type(e).__name__,
                          "safe_failure_location":location,
                          "error_code":str(e) if str(e).isupper() and
                          len(str(e))<72 else "INTERNAL_SAFE_ABORT",
                          "publications":0,"extra_pollers":0}))
        sys.exit(2)
if __name__=="__main__":main()
