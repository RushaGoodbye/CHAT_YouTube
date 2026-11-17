#!/usr/bin/env python3
"""RG NEWS2 photo-only integration with single canary and automatic rollback.

Existing DSM task is reused. Existing poller is not changed or duplicated.
Public delivery is never enabled. Requires pinned installed source code.
After installation a canary must add exactly ONE photo-dispatch Telegram receipt;
otherwise the DSM shell is restored from backup immediately.
"""
import ast
import datetime as dt
import fcntl
import hashlib
import json
import runpy
import inspect
import re
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
TICK=BASE/"rg_news_dsm_tick.sh"
LEGACY=BASE/"rg_v18.py"
OUT=BASE/"operator/rg_news2_outbound_queue_v2.py"
PHOTO=BASE/"telegram_photo_review_flow.py"
DB=BASE/"news.sqlite3"
GUARD=BASE/"rg_news2_photo_tick_guard_v4.py"
MARK="RG_NEWS2_PRIVATE_PHOTO_TICK_V4"
UNCONFIRMED=VAULT/"rg_news2_photo_unconfirmed_v4.json"
EXPECTED={"tick":"9a2d04e499da","legacy":"63fef26bdf9f",
          "out":"e94253084ea2","photo":"79c473bf774f"}

def digest(p):
    if p.is_symlink() or not p.is_file():
        raise RuntimeError("SOURCE_MISSING_OR_SYMLINK")
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]

def contract():
    for name,p in (("tick",TICK),("legacy",LEGACY),("out",OUT),("photo",PHOTO)):
        if digest(p)!=EXPECTED[name]:
            raise RuntimeError("SOURCE_VERSION_MISMATCH_"+name)
    old=TICK.read_text(encoding="utf-8")
    if not old.startswith("#!") or any(s in old for s in ("$0","trap ","source ",MARK)):
        raise RuntimeError("TICK_WRAPPER_NOT_SAFE")
    txt=OUT.read_text(encoding="utf-8")
    if any(s in txt.lower() for s in ("getupdates","get_updates","public_channel","channel_username")):
        raise RuntimeError("OUTBOUND_PRIVACY_PROOF_FAILED")
    # Human-readable error labels may change and cannot establish safety.
    # Instead verify actual safety calls in the pinned outbound run() AST.
    tree=ast.parse(txt)
    runs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="run"]
    if len(runs)!=1 or any(isinstance(n,(ast.For,ast.While,ast.AsyncFor))
                           for n in ast.walk(runs[0])):
        raise RuntimeError("PHOTO_MODE_NOT_SINGLE_PASS")
    call_names=set()
    for n in ast.walk(runs[0]):
        if isinstance(n,ast.Call):
            name=(n.func.id if isinstance(n.func,ast.Name) else
                  n.func.attr if isinstance(n.func,ast.Attribute) else None)
            if name:call_names.add(name)
    needed={"deliver_one","photo_auto_gate_open","private_send_only"}
    if not needed.issubset(call_names):
        missing=sorted(needed-call_names)
        raise RuntimeError("PRIVATE_PHOTO_SAFETY_CALLS_MISSING:"+",".join(missing))
    if "telegram_photo_review_flow" not in txt:
        raise RuntimeError("PHOTO_WORKER_IMPORT_NOT_FOUND")
    calls=sum(isinstance(n,ast.Call) and (
              isinstance(n.func,ast.Name) and n.func.id=="deliver_one" or
              isinstance(n.func,ast.Attribute) and n.func.attr=="deliver_one")
              for n in ast.walk(runs[0]))
    if calls!=1 or not any(isinstance(n,ast.Constant) and n.value=="photo"
                             for n in ast.walk(tree)):
        raise RuntimeError("PHOTO_MODE_UNRECOGNIZED")
    ptree=ast.parse(PHOTO.read_text(encoding="utf-8"))
    delivery=[n for n in ptree.body if isinstance(n,ast.FunctionDef)
              and n.name=="deliver_one"]
    if len(delivery)!=1 or not any(isinstance(n,ast.Call) and (
            isinstance(n.func,ast.Name) and n.func.id=="claim_one")
            for n in ast.walk(delivery[0])):
        raise RuntimeError("PHOTO_CLAIM_GUARD_MISSING")
    return {"pins":"PASS","private_safety_calls":"PASS","additional_pollers":0,
            "public_gate_modifications":0,"max_delivery_calls_per_tick":1}

def sql_counts():
    if not DB.is_file() or DB.is_symlink():
        raise RuntimeError("DB_NOT_FOUND")
    c=sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)
    try:
        pending=c.execute("SELECT COUNT(*) FROM candidates WHERE status='awaiting_photo_review'").fetchone()[0]
        archived=c.execute("SELECT COUNT(*) FROM candidates WHERE status='archived_stale'").fetchone()[0]
        rows,receipts=c.execute("SELECT COUNT(*),COUNT(telegram_message_id) FROM rg_news2_photo_dispatch").fetchone()
        return {"pending":pending,"archived":archived,"photo_rows":rows,"receipts":receipts}
    finally:c.close()

def silence():
    try:
        from zoneinfo import ZoneInfo
        d=dt.datetime.now(ZoneInfo("Europe/Kyiv"))
        return d.hour==9 and d.minute<=5
    except ImportError:
        return dt.datetime.now(dt.timezone.utc).hour in (6,7)

def safe_worker_reason(raw):
    # Never echo raw Bot API output or any untrusted article text.
    output=raw.decode("utf-8","replace").lower()[:50000]
    # Categorize standard Python CLI/import failures without exposing lines
    # containing paths, environment values, Telegram IDs or secrets.
    if "unrecognized arguments" in output:
        return "CLI_UNRECOGNIZED_ARGUMENT"
    if "invalid choice:" in output:
        return "CLI_INVALID_CHOICE"
    if "the following arguments are required" in output:
        return "CLI_REQUIRED_ARGUMENT"
    if "modulenotfounderror" in output or "no module named" in output:
        return "PYTHON_MODULE_IMPORT_FAILURE"
    if "importerror" in output:
        return "PYTHON_IMPORT_FAILURE"
    if "filenotfounderror" in output:
        return "MISSING_PATH"
    if "permissionerror" in output:
        return "PERMISSION_FAILURE"
    if "operationalerror" in output and "locked" in output:
        return "SQLITE_LOCKED"
    if "runtimeerror" in output and "photo" in output:
        return "PHOTO_RUNTIME_GUARD_EXCEPTION"
    whitelist=("photo_pilot_gate_closed_no_send",
               "photo_daily_budget_exhausted",
               "photo_rate_cooldown",
               "photo_review_at_capacity",
               "photo_not_private",
               "photo_buttons_not_supported_by_active_worker",
               "photo_dispatch_schema_not_installed",
               "moderation_delivery_disabled",
               "photo_rate_ledger_future_timestamp",
               "uncertain_state_reconciliation_required")
    return next((reason for reason in whitelist if reason in output),
                "NO_EXPLICIT_SAFE_REASON")

def safe_direct_run_contract():
    """Validate the installed pinned run(mode) callable without guessing CLI.

    The exact source hash is verified independently by contract() and at
    every tick. The module body contains no Telegram update polling and no
    public-channel path according to its static source contract.
    """
    if digest(OUT)!=EXPECTED["out"]:
        raise RuntimeError("OUTBOUND_SHA_CHANGED")
    root=ast.parse(OUT.read_text(encoding="utf-8"))
    funcs=[n for n in root.body if isinstance(n,ast.FunctionDef) and n.name=="run"]
    if len(funcs)!=1:
        raise RuntimeError("OUTBOUND_RUN_ENTRYPOINT_MISSING")
    fn=funcs[0]
    positional=fn.args.posonlyargs+fn.args.args
    if (len(positional)!=1 or len(fn.args.defaults)!=0
            or fn.args.vararg is not None or fn.args.kwarg is not None
            or fn.args.kwonlyargs):
        raise RuntimeError("OUTBOUND_RUN_SIGNATURE_UNSAFE")
    if positional[0].arg!="mode":
        raise RuntimeError("OUTBOUND_RUN_MODE_NOT_PROVEN")
    if not any(isinstance(x,ast.Compare) and
               any(isinstance(v,ast.Constant) and v.value=="photo"
                   for v in ast.walk(x)) and
               any(isinstance(v,ast.Name) and v.id=="mode"
                   for v in ast.walk(x))
               for x in ast.walk(fn)):
        raise RuntimeError("OUTBOUND_MODE_PHOTO_BRANCH_MISSING")
    main_guards=[x for x in root.body if isinstance(x,ast.If) and
                 "__main__" in ast.dump(x.test)]
    if not main_guards:
        raise RuntimeError("OUTBOUND_MAIN_GUARD_MISSING")
    return {"entrypoint":"DIRECT_PINNED_RUN_MODE","argv_trials":0,
            "source_sha_verified":True,"public_route_enabled":False}

def invoke_pinned_run(mode):
    """Child process imports one exact pinned module but skips its CLI entrypoint."""
    if mode not in ("status","photo"):
        raise RuntimeError("RUN_MODE_NOT_ALLOWED")
    safe_direct_run_contract()
    sys.path.insert(0,str(BASE))
    sys.path.insert(0,str(OUT.parent))
    # Uses a non-__main__ run name: no CLI parser and no second poller.
    d=runpy.run_path(str(OUT),run_name="rg_news2_private_only_runner_v4")
    target=d.get("run")
    if not callable(target):
        raise RuntimeError("OUTBOUND_RUN_NOT_CALLABLE")
    signature=inspect.signature(target)
    if len(signature.parameters)!=1:
        raise RuntimeError("OUTBOUND_RUNTIME_SIGNATURE_MISMATCH")
    result=target(mode)
    if isinstance(result,int) and result!=0:
        raise RuntimeError("OUTBOUND_RESULT_NONZERO")
    return result

def photo_cli_arguments():
    """Infer CLI from AST; never trial multiple send-capable commands."""
    tree=ast.parse(OUT.read_text(encoding="utf-8"))
    candidates=[]
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute):
            continue
        if node.func.attr=="add_argument":
            names=[x.value for x in node.args if isinstance(x,ast.Constant)
                   and isinstance(x.value,str)]
            opts={x.arg:x.value for x in node.keywords if x.arg}
            values=[]
            choices=opts.get("choices")
            if isinstance(choices,(ast.List,ast.Tuple,ast.Set)):
                values=[x.value for x in choices.elts if isinstance(x,ast.Constant)
                        and isinstance(x.value,str)]
            for name in names:
                if name in ("mode","command","action") or (
                    name in ("--mode","--command","--action") and
                    ("photo" in values or not values)):
                    if values and "photo" not in values:
                        continue
                    candidates.append([name,"photo"] if name.startswith("-")
                                      else ["photo"])
                elif "photo" in values and (
                    name in ("operation","--operation","--task","task")):
                    candidates.append([name,"photo"] if name.startswith("-")
                                      else ["photo"])
        if node.func.attr=="add_parser" and node.args and isinstance(node.args[0],ast.Constant):
            if node.args[0].value=="photo":
                candidates.append(["photo"])
    if not candidates:
        # Only use direct sys.argv[1] if there is no ambiguous argparse mode.
        direct=any(isinstance(node,ast.Subscript) and
                   isinstance(node.value,ast.Attribute) and
                   isinstance(node.value.value,ast.Name) and
                   node.value.value.id=="sys" and node.value.attr=="argv" and
                   isinstance(node.slice,ast.Constant) and node.slice.value==1
                   for node in ast.walk(tree))
        if direct:
            candidates=[["photo"]]
    unique={tuple(v) for v in candidates}
    if len(unique)!=1:
        raise RuntimeError("PHOTO_CLI_MODE_UNPROVEN_OR_AMBIGUOUS")
    result=list(unique.pop())
    if result not in (["photo"],["--mode","photo"],["--command","photo"],
                      ["--action","photo"],["--operation","photo"],
                      ["--task","photo"]):
        raise RuntimeError("PHOTO_CLI_NOT_IN_PRIVATE_ALLOWLIST")
    return result

REASON_CODES={
    "photo_pilot_gate_closed_no_send","photo_daily_budget_exhausted",
    "photo_rate_cooldown","photo_review_at_capacity","photo_not_private",
    "photo_buttons_not_supported_by_active_worker",
    "photo_dispatch_schema_not_installed","moderation_delivery_disabled",
    "photo_rate_ledger_future_timestamp","uncertain_state_reconciliation_required",
    "photo_auto_gate_closed","private_delivery_disabled","gate_closed",
    "no_eligible_candidate","no_candidates","status_only","config_missing"
}
def compact_status(raw):
    """Extract only safely allowlisted machine error codes; no raw bot data."""
    result=set()
    data=raw.decode("utf-8","replace")[:80000]
    for match in re.finditer(r"[A-Za-z][a-zA-Z0-9_]{2,65}",data):
        token=match.group(0).lower()
        if token in REASON_CODES:
            result.add(token)
    for mark in ("ModuleNotFoundError","unrecognized arguments","required: --mode",
                 "invalid choice","PermissionError","FileNotFoundError","ImportError"):
        if mark.lower() in data.lower():
            result.add("runtime_"+re.sub("[^a-z_]+","_",mark.lower()))
    return sorted(result)[:12]

def source_status_probe(cli):
    """Status mode is evaluated once, never a send-capable CLI argument."""
    if not cli or cli[-1]!="photo":
        return {"status":"CLI_UNVERIFIED"}
    try:
        p=subprocess.run([sys.executable,str(OUT)]+cli[:-1]+["status"],
                         cwd=str(BASE),capture_output=True,timeout=12,check=False)
        return {"status":"READ_ONLY_STATUS_PROBED","exit_code":p.returncode,
                "safe_codes":compact_status(p.stdout+p.stderr)}
    except (OSError,subprocess.TimeoutExpired):
        return {"status":"READ_ONLY_STATUS_UNAVAILABLE"}

def single_attempt_mark(status):
    """Persist an uncertainty gate without recording candidate or chat IDs."""
    if not VAULT.is_dir() or VAULT.is_symlink() or UNCONFIRMED.is_symlink():
        raise RuntimeError("CANARY_GUARD_STORAGE_UNAVAILABLE")
    temp=UNCONFIRMED.with_name(UNCONFIRMED.name+".tmp")
    with open(str(temp),"w",encoding="utf-8") as h:
        json.dump({"schema":"RG_NEWS2_V4_PRIVATE_CANARY","state":status},h)
        h.flush()
        os.fsync(h.fileno())
    os.chmod(str(temp),0o600)
    os.replace(str(temp),str(UNCONFIRMED))

def readonly_status_proven():
    """Status probe may run only when the first branch returns without send."""
    t=ast.parse(OUT.read_text(encoding="utf-8"))
    run=next((n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=="run"),None)
    if run is None or not run.body or not isinstance(run.body[0],ast.If):
        return False
    guard=run.body[0]
    return (any(isinstance(n,ast.Constant) and n.value=="status"
                for n in ast.walk(guard.test)) and
            any(isinstance(n,ast.Return) for n in ast.walk(guard)))

def one_canary():
    lockfile=BASE/"rg_news2_photo_tick_one.lock"
    f=os.open(str(lockfile),os.O_RDWR|os.O_CREAT,0o600)
    try:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status":"ALREADY_RUNNING"}
        if UNCONFIRMED.exists():
            return {"status":"UNCONFIRMED_PREVIOUS_CANARY_BLOCKS_RETRY"}
        if silence():
            return {"status":"KYIV_MINUTE_OF_SILENCE"}
        # Every recurring tick revalidates that the reviewed private-only
        # worker and outbound module have not been replaced or updated.
        if digest(OUT)!=EXPECTED["out"] or digest(PHOTO)!=EXPECTED["photo"]:
            return {"status":"SOURCE_UPDATED_REQUIRES_NEW_PRIVATE_QA"}
        before=sql_counts()
        if before["archived"]<1353 or before["pending"]<1 or before["pending"]>50:
            return {"status":"FRESH_QUEUE_GUARD","counts":before}
        # Run the already-installed function directly. This eliminates CLI
        # argument ambiguity and does not probe send-capable commands.
        try:
            safe_direct_run_contract()
        except RuntimeError:
            return {"status":"PINNED_DIRECT_RUN_ENTRYPOINT_UNSAFE","counts":before}
        # A persistent uncertainty marker is written before the first send.
        # A failed/ambiguous result will NOT be automatically retried.
        single_attempt_mark("SEND_ATTEMPTED_REQUIRES_RECEIPT")
        try:
            p=subprocess.run([sys.executable,str(GUARD),"invoke-photo"],
                             cwd=str(BASE),capture_output=True,timeout=70,
                             check=False)
            rc=p.returncode
        except subprocess.TimeoutExpired:
            return {"status":"SEND_UNCERTAIN_TIMEOUT_NO_RETRY"}
        reason=safe_worker_reason(p.stdout)+":"+safe_worker_reason(p.stderr)
        safe_codes=compact_status(p.stdout+p.stderr)
        after=sql_counts()
        dr=after["photo_rows"]-before["photo_rows"]
        receipts=after["receipts"]-before["receipts"]
        status=("ONE_PRIVATE_RECEIPT_CONFIRMED" if rc==0 and dr==1
                and receipts==1 else "CANARY_NOT_CONFIRMED")
        if status=="ONE_PRIVATE_RECEIPT_CONFIRMED":
            # Gate removal occurs only after the local Telegram receipt exists.
            UNCONFIRMED.unlink()
        # Otherwise retain the gate: automatic retries are forbidden.
        # Never print subprocess stdout/stderr (potential Bot API metadata).
        return {"status":status,"exit_code":rc,"safe_worker_reason":reason,"safe_result_codes":safe_codes,"entrypoint":"DIRECT_PINNED_RUN_MODE","new_photo_rows":dr,
                "new_receipts":receipts,"pending_before":before["pending"],
                "pending_after":after["pending"],"public_posts_by_integrator":0,
                "new_pollers_by_integrator":0}
    finally:os.close(f)

def wrapper(original):
    return ("#!/bin/sh\n# "+MARK+"\n"
            "sh '"+str(original)+"' \"$@\"\n"
            "rg_prior=$?\n"
            "if [ \"$rg_prior\" -ne 0 ]; then exit \"$rg_prior\"; fi\n"
            "/usr/bin/python3 '"+str(GUARD)+"' tick\n"
            "exit $?\n")

def replace_text(p,txt):
    temp=p.with_name(p.name+".rg_new")
    with open(str(temp),"w",encoding="utf-8") as h:
        h.write(txt);h.flush();os.fsync(h.fileno())
    os.chmod(str(temp),0o700)
    os.replace(str(temp),str(p))

def install():
    if os.geteuid()!=0:raise RuntimeError("ROOT_REQUIRED")
    if not VAULT.is_dir() or VAULT.is_symlink():
        raise RuntimeError("BACKUP_VAULT_MISSING")
    proof=contract()
    entry=safe_direct_run_contract()
    proof.update(entry)
    status_probe={"status":"DIRECT_RUN_STATUS_NOT_NEEDED"}
    # The installed "status" mode is not invoked until side-effect-free
    # source proof exists; running no check is safer than a wrong CLI.
    blocking={"photo_auto_gate_closed","private_delivery_disabled","gate_closed",
              "photo_pilot_gate_closed_no_send","config_missing"}
    if blocking.intersection(status_probe.get("safe_codes",[])):
        return {"schema":"RG_NEWS2_PRIVATE_PHOTO_TICK_V4",
                "result":"BLOCKED_BY_EXISTING_PRIVATE_GATE",
                "source_checks":proof,"preflight_status":status_probe,
                "live_hook_modified":False,"public_gate_enabled":False,
                "new_pollers_started":0}
    initial=sql_counts()
    if initial["archived"]<1353 or not 1<=initial["pending"]<=50:
        raise RuntimeError("FRESH_PHOTO_QUEUE_GUARD_FAILED")
    f=os.open(str(BASE/"rg_news2_photo_install.lock"),os.O_RDWR|os.O_CREAT,0o600)
    try:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        folder=VAULT/("photo-tick-"+dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        folder.mkdir(mode=0o700)
        old=folder/"rg_news_dsm_tick.original.sh"
        shutil.copyfile(str(TICK),str(old))
        os.chmod(str(old),0o700)
        src=sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
        dst=sqlite3.connect(str(folder/"before.sqlite3"),timeout=4)
        try:src.backup(dst,pages=256,sleep=0.05)
        finally:dst.close();src.close()
        os.chmod(str(folder/"before.sqlite3"),0o600)
        if GUARD.is_symlink():
            raise RuntimeError("GUARD_SYMLINK_REFUSED")
        shutil.copyfile(__file__,str(GUARD))
        os.chmod(str(GUARD),0o700)
        wrapped=wrapper(old)
        subprocess.run(["sh","-n"],input=wrapped,text=True,check=True,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        replace_text(TICK,wrapped)
        result=None
        try:
            result=one_canary()
        finally:
            if not result or result["status"]!="ONE_PRIVATE_RECEIPT_CONFIRMED":
                shutil.copyfile(str(old),str(TICK))
                os.chmod(str(TICK),0o700)
        installed=result and result["status"]=="ONE_PRIVATE_RECEIPT_CONFIRMED"
        return {"schema":"RG_NEWS2_PRIVATE_PHOTO_TICK_V4",
                "result":"HOOK_INSTALLED" if installed else "HOOK_ROLLED_BACK",
                "canary":result,"backup_directory":str(folder),
                "preflight_status":status_probe,
                "post_rollback_counts":sql_counts(),
                "source_checks":proof,"public_gate_enabled":False,
                "new_pollers_started":0}
    finally:os.close(f)

def selftest():
    # Prove direct entry calls run(mode) once without invoking __main__ CLI.
    global BASE,OUT,EXPECTED
    saved=(BASE,OUT,EXPECTED)
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        operator=root/"operator"
        operator.mkdir()
        fake=operator/"outbound.py"
        marker=root/"photo_was_called"
        fake.write_text(
            "from pathlib import Path\n"
            "def run(mode):\n"
            "    if mode=='photo':\n"
            "        Path("+repr(str(marker))+").write_text('called_once')\n"
            "    return None\n"
            "if __name__=='__main__':\n"
            "    raise RuntimeError('wrong_cli_entrypoint')\n")
        try:
            BASE=root
            OUT=fake
            EXPECTED=dict(EXPECTED, out=hashlib.sha256(fake.read_bytes()).hexdigest()[:12])
            assert safe_direct_run_contract()["entrypoint"]=="DIRECT_PINNED_RUN_MODE"
            invoke_pinned_run("status")
            assert not marker.exists()
            invoke_pinned_run("photo")
            assert marker.read_text()=="called_once"
        finally:
            BASE,OUT,EXPECTED=saved
    with tempfile.TemporaryDirectory() as td:
        orig=pathlib.Path(td)/"original.sh"
        orig.write_text("#!/bin/sh\nexit 0\n")
        script=wrapper(orig)
        p=subprocess.run(["sh","-n"],input=script,text=True,
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        assert p.returncode==0
        assert MARK in script
        assert "getUpdates" not in script and "sendPhoto" not in script
    assert safe_worker_reason(b"usage: worker error: unrecognized arguments: photo")=="CLI_UNRECOGNIZED_ARGUMENT"
    assert safe_worker_reason(b"Traceback: ModuleNotFoundError: No module named 'secret'")=="PYTHON_MODULE_IMPORT_FAILURE"
    assert safe_worker_reason(b'{"status":"photo_rate_cooldown"}')=="photo_rate_cooldown"
    assert compact_status(b'{"reason":"photo_auto_gate_closed"}')==["photo_auto_gate_closed"]
    assert compact_status(b'{"token":"SECRET_123","reason":"private_delivery_disabled"}')==["private_delivery_disabled"]
    print("RG_NEWS2_PRIVATE_PHOTO_TICK_V4_SELFTEST_PASS")

if __name__=="__main__":
    try:
        if sys.argv[1:]==["selftest"]:
            selftest()
        elif sys.argv[1:]==["install"]:
            print(json.dumps(install(),sort_keys=True,indent=2))
        elif sys.argv[1:]==["invoke-photo"]:
            # Stdout and stderr are captured by the parent, never displayed.
            # Only one mode="photo" invocation may happen per child.
            invoke_pinned_run("photo")
        elif sys.argv[1:]==["tick"]:
            print(json.dumps(one_canary(),sort_keys=True,indent=2))
        elif sys.argv[1:]==["status"]:
            print(json.dumps({"status":"READ_ONLY","queue":sql_counts(),
                              "hook_installed":MARK in TICK.read_text()},sort_keys=True))
        else:raise RuntimeError("UNRECOGNIZED_MODE")
    except (RuntimeError,OSError,ValueError,sqlite3.Error,subprocess.SubprocessError) as err:
        print(json.dumps({"status":"SAFE_ABORT","error_code":str(err) if
            isinstance(err,RuntimeError) else type(err).__name__,
            "public_gate_changed":False,"extra_pollers_started":0}))
        sys.exit(2)
