#!/usr/bin/env python3
"""NEWS2 missing moderator photos: NAS-only read-only diagnosis.

No importing production modules, no sends, no Bot API, no DB mutations,
no schedtask invocation. Python 3.8 compatible. No messages, IDs or URLs.
"""
import ast
import collections
import datetime as dt
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time

BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
OUT=BASE/"operator/rg_news2_outbound_queue_v2.py"
DB=BASE/"news.sqlite3"
TICK=BASE/"rg_news_dsm_tick.sh"
EXPECTED="e94253084ea2"
KNOWN={"awaiting_photo_review","awaiting_moderation","archived_stale",
       "rejected","sent","uncertain","sending","queued","claimed","pending",
       "delivered","photo_reviewed","accepted","accept","reject","approved",
       "failed","blocked","ready","photo_sent"}

def columns(conn,table):
    return {r[1] for r in conn.execute('PRAGMA table_info("'+table+'")')}

def read_db(path):
    if path.is_symlink() or not path.is_file():raise RuntimeError("DB_SOURCE_INVALID")
    c=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
    c.execute("PRAGMA query_only=ON")
    try:
        tables={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result={"read_only":True}
        for table in ("candidates","rg_news2_photo_dispatch",
                      "rg_v35_photo_audit","moderation_dispatch"):
            if table not in tables:continue
            fields=columns(c,table)
            row={"rows":c.execute('SELECT COUNT(*) FROM "'+table+'"').fetchone()[0]}
            if "status" in fields:
                counts=c.execute('SELECT status,COUNT(*) FROM "'+table+'" GROUP BY status').fetchall()
                labels={};other=0
                for key,n in counts:
                    if isinstance(key,str) and key in KNOWN:labels[key]=n
                    else:other+=n
                if other:labels["other_redacted"]=other
                row["statuses"]=labels
            if table=="rg_news2_photo_dispatch":
                if "telegram_message_id" in fields:
                    row["confirmed_receipts"]=c.execute(
                       "SELECT COUNT(*) FROM rg_news2_photo_dispatch WHERE telegram_message_id IS NOT NULL").fetchone()[0]
                candkey=next((x for x in ("candidate_id","news_id") if x in fields),None)
                if candkey and "candidates" in tables:
                    candcols=columns(c,"candidates")
                    if "id" in candcols:
                        out=c.execute(
                          'SELECT c.status,c.photo_reviewed FROM rg_news2_photo_dispatch d '
                          'LEFT JOIN candidates c ON c.id=d."'+candkey+'" '
                          'WHERE d.telegram_message_id IS NOT NULL').fetchall() if \
                          {"status","photo_reviewed"}.issubset(candcols) else []
                        row["receipt_linkage"]={
                            "linked_reviewed":sum(bool(x[1]) for x in out if x[0] is not None),
                            "linked_unreviewed":sum(not bool(x[1]) for x in out if x[0] is not None),
                            "unlinked":sum(x[0] is None for x in out),
                            "linked_awaiting_moderation":sum(x[0]=="awaiting_moderation" for x in out)}
                        if out:
                            row["photo_review_capacity_diagnostic"]="OPEN_REVIEW_CARDS_PRESENT" if row["receipt_linkage"]["linked_unreviewed"] else "NO_UNREVIEWED_CARDS_IN_RECEIPT_LEDGER"
                if "state" in fields:
                    classes=c.execute("SELECT state, COUNT(*) FROM rg_news2_photo_dispatch GROUP BY state").fetchall()
                    safe={};unknown=0
                    for k,n in classes:
                        if k in KNOWN:safe[k]=n
                        else:unknown+=n
                    if unknown:safe["other_redacted"]=unknown
                    row["states"]=safe
                times=next((n for n in ("created_at","sent_at","updated_at","delivered_at")
                            if n in fields),None)
                if times:
                    entries=c.execute('SELECT "'+times+'" FROM rg_news2_photo_dispatch').fetchall()
                    def as_sec(v):
                        if isinstance(v,(int,float)):
                            n=float(v)
                            if n>1e12:n/=1000
                            return n if n>946684800 else None
                        if isinstance(v,str):
                            try:
                                t=dt.datetime.fromisoformat(v.replace("Z","+00:00"))
                                if t.tzinfo is None:
                                    t=t.replace(tzinfo=dt.timezone.utc)
                                return t.timestamp()
                            except (ValueError,OverflowError):return None
                        return None
                    stamps=[z for x in entries for z in [as_sec(x[0])] if z is not None]
                    if stamps:
                        now=time.time()
                        row["receipts_last_24h"]=sum(0<=now-x<=86400 for x in stamps)
                        row["latest_receipt_age_minutes"]=round(max(0,now-max(stamps))/60,1)
            if table=="candidates" and "photo_reviewed" in fields:
                row["photo_reviewed_true"]=c.execute(
                      "SELECT COUNT(*) FROM candidates WHERE photo_reviewed=1").fetchone()[0]
            if table=="rg_v35_photo_audit":
                col=next((x for x in ("action","status","result","decision")
                          if x in fields),None)
                if col:
                    n=c.execute('SELECT "'+col+'",COUNT(*) FROM rg_v35_photo_audit GROUP BY "'+col+'"').fetchall()
                    row["actions"]={str(k):v for k,v in n if k in ("accept","reject","accepted","rejected")}
            result[table]=row
        return result
    finally:c.close()

def source_report(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("SENDER_SOURCE_NOT_REGULAR")
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()[:12]!=EXPECTED:
        raise RuntimeError("SENDER_SOURCE_SHA_CHANGED")
    t=ast.parse(raw.decode("utf-8"))
    globals={}
    for n in t.body:
        target=None;value=None
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            target=n.targets[0].id;value=n.value
        if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name):
            target=n.target.id;value=n.value
        if target in ("PHOTO_MAX_PER_24_HOURS", "PHOTO_RATE_COOLDOWN_SECONDS",
                      "PHOTO_MAX_PENDING", "PHOTO_REVIEW_CAPACITY", "PHOTO_RATE_LIMIT"):
            if isinstance(value,ast.Constant) and isinstance(value.value,(float,int)):
                if 0<=value.value<=86400:globals[target]=value.value
            elif isinstance(value,ast.Num) and 0<=value.n<=86400:
                globals[target]=value.n
            else:globals[target]="DYNAMIC"
    f=next((x for x in t.body if isinstance(x,ast.FunctionDef) and x.name=="run"),None)
    if not f:raise RuntimeError("PINNED_RUN_FUNCTION_MISSING")
    gate_vars=("photo_open","ordinary_open","last24","cooldown",
               "PHOTO_MAX_PER_24_HOURS","accepted_waiting")
    guard_flags={}
    for key in gate_vars:
        lines=[n.lineno for n in ast.walk(f) if isinstance(n,ast.If) and
          any(isinstance(x,ast.Name) and x.id==key for x in ast.walk(n.test))]
        if lines:guard_flags[key]=sorted(lines)
    return {"pinned":True,"limits_from_source":globals,
            "guard_lines":guard_flags,
            "no_sender_executed":True}

def scheduler():
    hook=TICK.is_file() and not TICK.is_symlink()
    raw=TICK.read_text() if hook else ""
    state={"hook_installed":"RG_NEWS2_PRIVATE_FINAL_V1" in raw,
           "single_wrapper_call":raw.count("rg_news2_private_final_guard_v1.py")==1,
           "legacy_preserved":"rg_prior=$?" in raw,
           "shell_syntax_ok":False}
    if hook:
        try:
            r=subprocess.run(["/bin/sh","-n",str(TICK)],
                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
            state["shell_syntax_ok"]=r.returncode==0
        except (OSError,subprocess.TimeoutExpired):pass
    cmd=next((x for x in ("/usr/syno/bin/synoschedtask","/usr/syno/sbin/synoschedtask")
              if os.path.isfile(x)),None)
    state["schedule"]={"checked":False}
    if cmd:
        try:
            p=subprocess.run([cmd,"--get"],stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,timeout=12)
            if p.returncode==0:
                import re
                rows=p.stdout.decode("utf-8","replace").splitlines()
                current=None;found={}
                for line in rows:
                    m=re.match(r"^\s*(ID|State|Status|Last Run Time|Command|Name):\s*(.*)$",line,re.I)
                    if not m:continue
                    k,v=m.groups();k=k.lower();v=v.strip().strip("[]")
                    if k=="id":
                        current=int(v) if v.isdigit() else None
                        if current==4:found={"checked":True,"task_found":True}
                        continue
                    if current!=4:continue
                    if k=="state":found["enabled"]=v.lower()=="enabled"
                    if k=="status":found["last_task_result"]=v.lower() if v.lower() in ("success","failed","running","error") else "unknown"
                    if k=="last run time":
                        try:
                            t=dt.datetime.strptime(v,"%a %b %d %H:%M:%S %Y")
                            found["last_task_age_minutes"]=round(max(0,(dt.datetime.now()-t).total_seconds())/60,1)
                        except ValueError:pass
                    if k in ("command","name"):
                        found["script_match"]=found.get("script_match",False) or "rg_news_dsm_tick.sh" in v
                state["schedule"]=found or {"checked":True,"task_found":False}
        except (OSError,subprocess.TimeoutExpired):state["schedule"]={"checked":False}
    return state

def report(base=BASE,vault=VAULT,expected=None):
    global EXPECTED
    if expected is not None:EXPECTED=expected
    db=read_db(base/"news.sqlite3")
    code=source_report(base/"operator/rg_news2_outbound_queue_v2.py")
    tick=scheduler() if base==BASE else {"test_fixture":True}
    uncertain=(vault/"rg_news2_private_final_unconfirmed_v1.json").is_file()
    pub=(vault/"rg_news2_photo_unconfirmed_v6.json").is_file()
    photo=db.get("rg_news2_photo_dispatch",{})
    queued=db.get("candidates",{}).get("statuses",{}).get("awaiting_photo_review")
    evidence={"schema":"RG_NEWS2_DELIVERY_BLOCKER_LIVE_V1",
              "read_only":True,"telegram_calls":0,"pollers_started":0,
              "publications":0,"sqlite_writes":0,
              "queue_pending_photo_review":queued,
              "photo_receipts":photo.get("confirmed_receipts"),
              "new_uncertainty_gate_present":uncertain,
              "old_v6_evidence_preserved":pub,
              "source_gate_summary":code,
              "photo_send_ledger":photo,
              "candidates":db.get("candidates"),
              "photo_audit":db.get("rg_v35_photo_audit"),
              "scheduler":tick}
    blockers=[]
    if uncertain:blockers.append("UNCERTAIN_SEND_BLOCKS_RETRY")
    if photo.get("receipt_linkage",{}).get("linked_unreviewed",0)>0:
        blockers.append("UNREVIEWED_SENT_PHOTO_CARDS_EXIST")
    limit=code["limits_from_source"].get("PHOTO_MAX_PER_24_HOURS")
    if isinstance(limit,(int,float)) and photo.get("receipts_last_24h",0)>=limit:
        blockers.append("PHOTO_DAILY_LIMIT_REACHED")
    if tick.get("hook_installed") is False:blockers.append("PRIVATE_HOOK_NOT_INSTALLED")
    if tick.get("shell_syntax_ok") is False:blockers.append("DSM_TICK_SHELL_INVALID")
    evidence["possible_blockers_not_runtime_proof"]=blockers
    evidence["next_step"]="Do not attempt resend without reconciling uncertainty and live gate values."
    return evidence

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        (root/"operator").mkdir()
        vault=root/"vault";vault.mkdir()
        db=root/"news.sqlite3"
        c=sqlite3.connect(str(db))
        c.execute("CREATE TABLE candidates(id INT,status TEXT,photo_reviewed INT)")
        c.executemany("INSERT INTO candidates VALUES(?,?,?)",[
          (1,"awaiting_photo_review",0),(2,"awaiting_moderation",1)])
        c.execute("CREATE TABLE rg_news2_photo_dispatch(candidate_id INT,telegram_message_id INT,state TEXT,created_at INT)")
        c.executemany("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?,?)",[
          (1,111,"sent",int(time.time())),(2,112,"sent",int(time.time()))])
        c.execute("CREATE TABLE rg_v35_photo_audit(action TEXT)")
        c.execute("INSERT INTO rg_v35_photo_audit VALUES ('accept')")
        c.commit();c.close()
        src=root/"operator/rg_news2_outbound_queue_v2.py"
        src.write_text("PHOTO_MAX_PER_24_HOURS=2\n"
          "def run(mode):\n"
          "  if photo_open>=1:return\n"
          "  if last24>=PHOTO_MAX_PER_24_HOURS:return\n")
        hash=hashlib.sha256(src.read_bytes()).hexdigest()[:12]
        data=report(root,vault,hash)
        assert data["queue_pending_photo_review"]==1
        assert data["photo_send_ledger"]["receipt_linkage"]["linked_unreviewed"]==1
        assert "PHOTO_DAILY_LIMIT_REACHED" in data["possible_blockers_not_runtime_proof"]
        assert "UNREVIEWED_SENT_PHOTO_CARDS_EXIST" in data["possible_blockers_not_runtime_proof"]
    print("RG_NEWS2_DELIVERY_BLOCKER_LIVE_V1_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:
        selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(report(),indent=2,sort_keys=True))
    else:sys.exit("Only selftest or inspect")
