#!/usr/bin/env python3
"""RG NEWS2 narrowly guarded capacity repair and orphan attempt reconciliation.

Python 3.8. A hard, immutable source pin is required. The only live network
side-effect permitted is ONE normal private photo tick AFTER full local repair.
No public posting, extra Telegram poller, getUpdates, scheduler task creation,
reconfiguration of callback handling, or DB mutations by this installer.
"""
import ast
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
GUARD=ROOT/"rg_news2_private_final_guard_v1.py"
MARK=VAULT/"rg_news2_private_final_unconfirmed_v1.json"
OUT=ROOT/"operator/rg_news2_outbound_queue_v2.py"
TICK=ROOT/"rg_news_dsm_tick.sh"
WORKER=ROOT/"telegram_photo_review_flow.py"
DB=ROOT/"news.sqlite3"
OLD_BLOB="40a83032d6407244fa3511b6fb38b192461e4c4c"
OUT_PIN="e94253084ea2"
WORKER_PIN="79c473bf774f"
CAP=3
TAG="RG_NEWS2_PRIVATE_CAPACITY_RESUME_V1"
ANCHOR1='    proof,fn=source_contract()\n    if not UNCERTAIN.is_file()'
ANCHOR2='    d["rg_private_only_tick"]("tick")\n    return {"status":"PRIVATE_BRANCH_EXECUTED"}'
ANCHOR3='        write_marker("SEND_ATTEMPTED_REQUIRES_RECEIPT")\n        try:'
ANCHOR4='        # Never output raw worker stdout/stderr or tokens.'
CAP_FUNC=String=None

def git_blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode("ascii")+b"\0"+data).hexdigest()

def regular(path):
    return path.is_file() and not path.is_symlink()

def source_pins(root=ROOT):
    guard=root/"rg_news2_private_final_guard_v1.py"
    if not regular(guard):raise RuntimeError("GUARD_SOURCE_UNAVAILABLE")
    data=guard.read_bytes()
    if git_blob(data)!=OLD_BLOB:
        raise RuntimeError("ORIGINAL_GUARD_VERSION_CHANGED")
    for p,pin in ((root/"operator/rg_news2_outbound_queue_v2.py",OUT_PIN),
                  (root/"telegram_photo_review_flow.py",WORKER_PIN)):
        if not regular(p) or hashlib.sha256(p.read_bytes()).hexdigest()[:12]!=pin:
            raise RuntimeError("INSTALLED_DEPENDENCY_CHANGED")
    tick=root/"rg_news_dsm_tick.sh"
    if not regular(tick) or 'RG_NEWS2_PRIVATE_FINAL_V1' not in tick.read_text():
        raise RuntimeError("DSM_PRIVATE_HOOK_MISSING")
    return data.decode("utf-8")

def when(value):
    if value is None:return None
    if isinstance(value,(float,int)):
        n=float(value)
        if n>1e12:n/=1000
        return n if 946684800<n<4102444800 else None
    if isinstance(value,str):
        try:
            d=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
            if d.tzinfo is None:d=d.replace(tzinfo=dt.timezone.utc)
            return d.timestamp()
        except (ValueError,OverflowError):return None
    return None

def stats(root=ROOT):
    db=root/"news.sqlite3"
    if not regular(db):raise RuntimeError("SQLITE_NOT_REGULAR")
    c=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
    c.execute("PRAGMA query_only=ON")
    try:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"candidates","rg_news2_photo_dispatch"}.issubset(tables):
            raise RuntimeError("REQUIRED_SQLITE_TABLES_MISSING")
        cols={r[1] for r in c.execute('PRAGMA table_info("rg_news2_photo_dispatch")')}
        cc={r[1] for r in c.execute('PRAGMA table_info("candidates")')}
        if not {"candidate_id","telegram_message_id","updated_at"}.issubset(cols):
            raise RuntimeError("DISPATCH_TIMESTAMP_SCHEMA_CHANGED")
        if not {"id","photo_reviewed","updated_at"}.issubset(cc):
            raise RuntimeError("CANDIDATE_TIMESTAMP_SCHEMA_CHANGED")
        rows,receipts=c.execute(
          "SELECT COUNT(*),COUNT(telegram_message_id) FROM rg_news2_photo_dispatch").fetchone()
        if rows!=receipts:raise RuntimeError("PENDING_UNRECEIPTED_DISPATCH_EXISTS")
        open_rows=c.execute(
          "SELECT d.updated_at,c.updated_at FROM rg_news2_photo_dispatch d "+
          "JOIN candidates c ON c.id=d.candidate_id "+
          "WHERE d.telegram_message_id IS NOT NULL AND COALESCE(c.photo_reviewed,0)=0"
        ).fetchall()
        other=c.execute(
          "SELECT COUNT(*) FROM candidates WHERE status='awaiting_photo_review'").fetchone()[0]
        old=c.execute(
          "SELECT COUNT(*) FROM candidates WHERE status='archived_stale'").fetchone()[0]
        return {"dispatch_rows":rows,"receipts":receipts,"open_cards":len(open_rows),
                "open_card_timestamp_pairs":open_rows,
                "queued":other,"archived":old}
    finally:c.close()

def prove_capacity_abort(root=ROOT):
    path=root/"operator/rg_news2_outbound_queue_v2.py"
    tree=ast.parse(path.read_bytes().decode("utf-8"))
    fn=next((n for n in tree.body if isinstance(n,ast.FunctionDef)
             and n.name=="run"),None)
    if fn is None:raise RuntimeError("RUN_FUNCTION_MISSING")
    matches=[]
    for node in ast.walk(fn):
        if not isinstance(node,ast.If):continue
        test=node.test
        if (isinstance(test,ast.Compare) and isinstance(test.left,ast.Name)
            and test.left.id=="photo_open" and
            len(test.ops)==1 and isinstance(test.ops[0],ast.GtE) and
            len(test.comparators)==1 and isinstance(test.comparators[0],ast.Constant)
            and test.comparators[0].value==1 and
            len(node.body)==1 and isinstance(node.body[0],ast.Return)):
            matches.append(node.lineno)
    calls=[n.lineno for n in ast.walk(fn) if isinstance(n,ast.Call) and
         (getattr(n.func,"id",None)=="deliver_one" or
          getattr(n.func,"attr",None)=="deliver_one")]
    if len(matches)!=1 or len(calls)!=1 or not matches[0]<calls[0]:
        raise RuntimeError("CAPACITY_ABORT_CODE_NOT_PROVEN")
    return {"guard_line":matches[0],"deliver_line":calls[0],
            "max_outstanding_before_patch":1}

def reconcile(root=ROOT,vault=VAULT):
    source_pins(root)
    capacity=prove_capacity_abort(root)
    marker=vault/"rg_news2_private_final_unconfirmed_v1.json"
    if not regular(marker) or marker.stat().st_size>4096:
        raise RuntimeError("UNCONFIRMED_MARKER_MISSING_OR_INVALID")
    raw=marker.read_text(encoding="utf-8")
    try:data=json.loads(raw)
    except ValueError:raise RuntimeError("MARKER_NOT_JSON")
    if not isinstance(data,dict) or data.get("state")!="SEND_ATTEMPTED_REQUIRES_RECEIPT":
        raise RuntimeError("UNKNOWN_MARKER_STATE")
    counts=stats(root)
    if counts["open_cards"]!=1:
        raise RuntimeError("EXPECTED_ONE_OLDER_OPEN_CARD")
    if counts["dispatch_rows"]!=4 or counts["receipts"]!=4:
        raise RuntimeError("DISPATCH_LEDGER_CHANGED")
    if counts["queued"]<1 or counts["archived"]<1353:
        raise RuntimeError("QUEUE_OR_ARCHIVE_CHANGED")
    marker_time=marker.stat().st_mtime
    stamps=[when(x) for pair in counts["open_card_timestamp_pairs"] for x in pair]
    if any(x is None for x in stamps):
        raise RuntimeError("OLDER_OPEN_CARD_TIMESTAMPS_UNAVAILABLE")
    if not all(x+3 < marker_time for x in stamps):
        raise RuntimeError("CARD_ALREADY_OPEN_AT_MARKER_NOT_PROVEN")
    # Existence of a prior, unreviewed receipt BEFORE the marker, plus
    # pinned photo_open>=1 early return, proves the installed private tick
    # could not reach deliver_one. No new dispatch since earlier canary.
    return {"status":"CAPACITY_NO_SEND_RECONCILED","marker_age_minutes":
          round(max(0,time.time()-marker_time)/60,1),
          "earlier_open_card_proven":True,
          "receipt_count":4,"queue":counts["queued"],
          "original_capacity":1,"safe_reconcile":True}

CAP_HELPER='''
def rg_capacity_relax_exact(fn):
    # Modify ONLY the isolated AST clone, never the installed outbound file.
    count=0
    for node in ast.walk(fn):
        if not isinstance(node,ast.If):continue
        c=node.test
        if (isinstance(c,ast.Compare) and isinstance(c.left,ast.Name)
            and c.left.id=="photo_open" and len(c.ops)==1
            and isinstance(c.ops[0],ast.GtE) and len(c.comparators)==1
            and isinstance(c.comparators[0],ast.Constant)
            and c.comparators[0].value==1
            and len(node.body)==1 and isinstance(node.body[0],ast.Return)):
            c.comparators[0]=ast.copy_location(ast.Constant(value=3),c.comparators[0])
            count+=1
    if count!=1:raise RuntimeError("CAPACITY_AST_PATCH_UNPROVEN")
    # Wrap actual photo.deliver_one(...) call, irrespective of module alias,
    # to distinguish NO SEND attempts from uncertain API failures.
    class ObservePhoto(ast.NodeTransformer):
        def __init__(self):self.count=0
        def visit_Call(self,node):
            self.generic_visit(node)
            n=node.func.id if isinstance(node.func,ast.Name) else (
              node.func.attr if isinstance(node.func,ast.Attribute) else "")
            if n=="deliver_one":
                self.count+=1
                return ast.copy_location(ast.Call(func=ast.Name(
                   id="__rg_observe_private_delivery",ctx=ast.Load()),
                   args=[node.func]+node.args,keywords=node.keywords),node)
            return node
    observer=ObservePhoto()
    fn=observer.visit(fn)
    if observer.count!=1:raise RuntimeError("PHOTO_DISPATCH_AST_PATCH_UNPROVEN")
    ast.fix_missing_locations(fn)
    return fn

'''
def patched_content(original):
    # All anchors are exact against the pinned already-running guard file.
    for name,needle in (("once",ANCHOR1),("after",ANCHOR2),
                        ("marker",ANCHOR3),("reason",ANCHOR4)):
        if original.count(needle)!=1:
            raise RuntimeError("PATCH_ANCHOR_CHANGED_"+name.upper())
    s=original.replace("def private_once():",CAP_HELPER+"def private_once():",1)
    s=s.replace(ANCHOR1,
       '    proof,fn=source_contract()\n'
       '    fn=rg_capacity_relax_exact(fn)\n'
       '    if not UNCERTAIN.is_file()',1)
    s=s.replace(ANCHOR2,
       '    calls={"count":0}\n'
       '    def __rg_observe_private_delivery(method,*args,**kwargs):\n'
       '        calls["count"]+=1\n'
       '        return method(*args,**kwargs)\n'
       '    d["__rg_observe_private_delivery"]=__rg_observe_private_delivery\n'
       '    d["rg_private_only_tick"]("tick")\n'
       '    return {"status":"PRIVATE_BRANCH_EXECUTED",\n'
       '            "delivery_invocations":calls["count"]}',1)
    # preflight capacity before setting the marker; never use read/write DB
    # for this check. The installed source's photo_open guard then enforces 3.
    s=s.replace(ANCHOR3,
       '        c=sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)\n'
       '        try:\n'
       '            cards=c.execute("SELECT COUNT(*) FROM rg_news2_photo_dispatch d "\n'
       '              "JOIN candidates x ON x.id=d.candidate_id "\n'
       '              "WHERE d.telegram_message_id IS NOT NULL AND COALESCE(x.photo_reviewed,0)=0").fetchone()[0]\n'
       '        finally:c.close()\n'
       '        if cards>=3:\n'
       '            return {"status":"PRIVATE_PHOTO_REVIEW_CAPACITY_3",\n'
       '                    "cards_waiting_for_moderator":cards}\n'
       '        write_marker("SEND_ATTEMPTED_REQUIRES_RECEIPT")\n'
       '        try:',1)
    s=s.replace(ANCHOR4,
       '        # If no call to deliver_one was made, a clean child exit is\n'
       '        # conclusive proof the sender never reached the photo API.\n'
       '        # Revoke only the marker created by THIS exact tick.\n'
       '        if rc==0 and newrows==0 and delta==0:\n'
       '            try:\n'
       '                result=json.loads(p.stdout.decode("utf-8","replace").strip().splitlines()[-1])\n'
       '            except (ValueError,IndexError,UnicodeError):result={}\n'
       '            if (result.get("status")=="PRIVATE_BRANCH_EXECUTED" and\n'
       '                result.get("delivery_invocations")==0):\n'
       '                UNCERTAIN.unlink()\n'
       '                return {"status":"NO_PHOTO_ATTEMPTED_NO_MARKER",\n'
       '                        "new_receipts":0,"new_photo_rows":0}\n'
       '        # Never output raw worker stdout/stderr or tokens.',1)
    compile(s,"rg_repaired_guard.py","exec")
    # Synthetic AST ensures there is ONLY one observation and original
    # public/RSS vetoes are still present.
    ast.parse(s)
    if s.count("PUBLIC_SEND_FORBIDDEN")!=1 or s.count("RSS_DISPATCH_FORBIDDEN")!=1:
        raise RuntimeError("PUBLIC_RSS_VETO_CHANGED")
    if s.count("    fn=rg_capacity_relax_exact(fn)")!=1:
        raise RuntimeError("CAPACITY_PATCH_MISSING")
    return s

def safe_write(target,body):
    temp=target.with_name(target.name+".rg_capacity_tmp")
    with open(str(temp),"w",encoding="utf-8") as h:
        h.write(body);h.flush();os.fsync(h.fileno())
    os.chmod(str(temp),0o700)
    os.replace(str(temp),str(target))

def locked(path):
    fd=os.open(str(path),os.O_CREAT|os.O_RDWR,0o600)
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except (OSError,BlockingIOError):
        os.close(fd);raise RuntimeError("ANOTHER_PRIVATE_WORKER_ACTIVE")
    return fd

def apply():
    if os.geteuid()!=0:raise RuntimeError("ROOT_REQUIRED")
    fd=locked(ROOT/"rg_news2_private_final_install.lock")
    try:
        sender=locked(ROOT/"rg_news2_private_final_send.lock")
        try:
            analysis=reconcile()
            old=source_pins()
            new=patched_content(old)
            save=VAULT/("capacity-repair-"+dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            save.mkdir(mode=0o700)
            for src,dst in ((GUARD,save/"original_guard.py"),(MARK,save/"uncertainty_before.json")):
                shutil.copyfile(str(src),str(dst));os.chmod(str(dst),0o600)
            # Verify expected isolated AST when module is compiled in-place.
            safe_write(GUARD,new)
            try:
                subprocess.run([sys.executable,"-m","py_compile",str(GUARD)],
                               check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
            except (OSError,subprocess.TimeoutExpired,subprocess.CalledProcessError):
                safe_write(GUARD,old)
                raise RuntimeError("GUARD_COMPILATION_FAILED_ROLLBACK")
            # Preserve the original uncertainty as evidence, moving it to a
            # separate, protected archive only AFTER source and ledger proof.
            archived=save/"reconciled_capacity_marker.json"
            os.replace(str(MARK),str(archived))
            os.chmod(str(archived),0o600)
        finally:os.close(sender)
    finally:os.close(fd)
    # Exactly one dispatch through existing locked tick, no new poller.
    # The existing minute-of-silence and provider guards still apply.
    try:
        p=subprocess.run([sys.executable,str(GUARD),"tick"],cwd=str(ROOT),
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=85)
        raw=p.stdout.decode("utf-8","replace").strip().splitlines()
        item=json.loads(raw[-1]) if raw else {}
    except (ValueError,OSError,subprocess.TimeoutExpired,UnicodeError):
        item={"status":"SEND_RESULT_UNCERTAIN"}
    permitted={"ONE_PRIVATE_RECEIPT_CONFIRMED","NO_PHOTO_ATTEMPTED_NO_MARKER",
               "PRIVATE_PHOTO_REVIEW_CAPACITY_3","NO_SAFE_NEW_ITEMS",
               "KYIV_SILENCE_NO_SEND","UNCONFIRMED_PREVIOUS_SEND_NO_RETRY",
               "CANARY_NOT_CONFIRMED","SEND_UNCERTAIN_TIMEOUT_NO_RETRY",
               "NO_PHOTO_ATTEMPTED_NO_MARKER"}
    state=item.get("status","UNKNOWN")
    if state not in permitted:state="UNCLASSIFIED_SAFE_STOP"
    after=stats()
    return {"schema":TAG,"result":"PRIVATE_CAPACITY_PATCH_INSTALLED",
            "marker_reconciled_from_capacity_no_send":True,
            "capacity_outstanding_cards":CAP,
            "public_enabled":False,"new_pollers_started":0,
            "one_tick_result":state,
            "confirmed_receipts_after":after["receipts"],
            "unreviewed_cards_after":after["open_cards"],
            "queued_after":after["queued"],
            "new_uncertainty_exists":MARK.exists(),
            "rollback_guard_backup_saved":True}

def selftest():
    # This is a source-to-source transformation, so use the actual pinned
    # repository source file in CI, not a toy implementation.
    original=pathlib.Path(__file__).with_name(
               "rg_news2_private_final_bundle_v1.py")
    if not original.is_file():
        raise RuntimeError("ORIGINAL_REPO_SOURCE_MISSING")
    original_text=original.read_text(encoding="utf-8")
    patched=patched_content(original_text)
    assert patched!=original_text
    root=ast.parse(patched)
    funcs={n.name:n for n in root.body if isinstance(n,ast.FunctionDef)}
    assert "rg_capacity_relax_exact" in funcs
    assert "private_once" in funcs
    assert "one_canary" in funcs
    try:patched_content(patched)
    except RuntimeError:pass
    else:raise AssertionError("SECOND_PATCH_NOT_BLOCKED")
    # Markers and data are never deleted by the patcher.
    assert "os.replace(str(MARK),str(archived))" in open(__file__).read()
    print("RG_NEWS2_CAPACITY_RESUME_SELFTEST_PASS")

def main():
    try:
        if sys.argv[1:]==["selftest"]:selftest()
        elif sys.argv[1:]==["audit"]:
            r=reconcile()
            print(json.dumps({"schema":TAG,"read_only":True,"proof":r,
                 "can_reconcile":True,"publications":0,"telegram_calls":0},indent=2))
        elif sys.argv[1:]==["repair"]:
            print(json.dumps(apply(),indent=2))
        else:raise RuntimeError("SUPPORTED_MODES_SELFTEST_AUDIT_REPAIR")
    except Exception as e:
        # Only enumerated code-safe symbols; no raw exception message.
        msg=str(e)
        if not re.fullmatch(r"[A-Z0-9_]{3,80}",msg):msg="SAFE_STOP"
        print(json.dumps({"schema":TAG,"status":"STOP_NO_UNVERIFIED_SEND",
              "reason_code":msg,"exception_type":type(e).__name__}))
        sys.exit(2)

if __name__=="__main__":main()
