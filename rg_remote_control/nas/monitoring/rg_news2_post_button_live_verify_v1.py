#!/usr/bin/env python3
"""RG NEWS2 callback + SQLite + DSM scheduler live, read-only verification.

Compatible with DSM /usr/bin/python3 (3.8). No production module imports,
no Telegram API, no getUpdates, no sends, no DB writes, no scheduler changes.
No text, IDs, tokens, URLs, raw commands or user content in output.
"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

APP=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
MON=pathlib.Path("/volume1/docker/RG_NAS_MONITOR")
BASELINE={"pre_canary_receipts":3, "post_canary_receipts":4,
          "post_canary_photo_rows":4, "archive_min":1353,
          "pre_button_moderation_dispatch":6, "pre_button_photo_audit":4}
TICK_MARK="RG_NEWS2_PRIVATE_FINAL_V1"
TICK_HASH="9a2d04e499da"
CALLBACK_HASH="0c48d2030e99"
GUARD_NAME="rg_news2_private_final_guard_v1.py"
GOOD_ACTION={"accept","accepted","approve","approved","reject","rejected",
             "photo_approved","photo_rejected","photo_reviewed",
             "accepted_for_moderation","awaiting_moderation"}
GOOD_STATUSES={"awaiting_photo_review","awaiting_moderation","archived_stale",
               "rejected","photo_reviewed","accepted","approved",
               "photo_rejected","photo_sent","uncertain","sending",
               "pending","delivered","sent"}
SQL_NAME=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,60}$")
TASK_FIELD=re.compile(r"^\s*(ID|State|Status|Last Run Time|Name|Command):\s*(.*)$",re.I)
SCHED_TASK=4

def sha12(path):
    if not path.is_file() or path.is_symlink():return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]

def quote(name):
    if not SQL_NAME.fullmatch(name):raise ValueError("UNSAFE_SQL_IDENTIFIER")
    return '"'+name+'"'

def columns(conn,table):
    return {row[1] for row in conn.execute("PRAGMA table_info("+quote(table)+")")}

def safe_count(conn,table):
    return conn.execute("SELECT COUNT(*) FROM "+quote(table)).fetchone()[0]

def count_status(conn,table,field):
    values=conn.execute("SELECT "+quote(field)+",COUNT(*) FROM "+
                        quote(table)+" GROUP BY "+quote(field)).fetchall()
    safe={}
    unknown=0
    for value,count in values:
        label=str(value).lower() if value is not None else ""
        if label in GOOD_STATUSES or label in GOOD_ACTION:
            safe[label]=count
        else:unknown+=count
    if unknown:safe["other_redacted"]=unknown
    return safe

def ledger(db):
    if not db.is_file() or db.is_symlink():
        return {"available":False}
    conn=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
    conn.execute("PRAGMA query_only=ON")
    try:
        tables={row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        out={"available":True,"read_only":True}
        for name in ("candidates","rg_news2_photo_dispatch",
                     "rg_v35_photo_audit","moderation_dispatch"):
            if name not in tables:continue
            fields=columns(conn,name)
            info={"rows":safe_count(conn,name)}
            if name=="candidates":
                if "status" in fields:
                    info["statuses"]=count_status(conn,name,"status")
                if "photo_reviewed" in fields:
                    info["photo_reviewed_true"]=conn.execute(
                        "SELECT COUNT(*) FROM candidates WHERE photo_reviewed=1"
                    ).fetchone()[0]
                if "photo_review_note" in fields:
                    info["photo_review_notes_nonempty"]=conn.execute(
                        "SELECT COUNT(*) FROM candidates WHERE "+
                        "photo_review_note IS NOT NULL AND "+
                        "TRIM(CAST(photo_review_note AS TEXT))<>''"
                    ).fetchone()[0]
            elif name=="rg_news2_photo_dispatch":
                if "telegram_message_id" in fields:
                    info["receipts"]=conn.execute(
                        "SELECT COUNT(*) FROM rg_news2_photo_dispatch "+
                        "WHERE telegram_message_id IS NOT NULL"
                    ).fetchone()[0]
                # Correlate the newest sent photo with its candidate, but
                # never expose actual Telegram/candidate identifiers.
                key=next((n for n in ("candidate_id","news_id") if n in fields),None)
                if key and "candidates" in tables:
                    cfields=columns(conn,"candidates")
                    last=conn.execute("SELECT "+quote(key)+
                      " FROM rg_news2_photo_dispatch ORDER BY rowid DESC LIMIT 1").fetchone()
                    if last is not None and last[0] is not None:
                        ident="id" if "id" in cfields else None
                        if ident:
                            wanted=["status","photo_reviewed","photo_review_note"]
                            wanted=[n for n in wanted if n in cfields]
                            result=conn.execute("SELECT "+
                              ",".join(quote(n) for n in wanted)+
                              " FROM candidates WHERE "+quote(ident)+"=? LIMIT 1",
                              (last[0],)).fetchone() if wanted else None
                            probe={"linked":result is not None}
                            if result:
                                d=dict(zip(wanted,result))
                                probe["status"]=d.get("status") if d.get("status") in GOOD_STATUSES else "other_redacted"
                                if "photo_reviewed" in d:
                                    probe["photo_reviewed"]=bool(d["photo_reviewed"])
                                if "photo_review_note" in d:
                                    probe["review_note_present"]=bool(str(d["photo_review_note"]).strip() if d["photo_review_note"] is not None else "")
                            info["newest_photo_candidate"]=probe
            else:
                action_key=next((n for n in ("action","decision","event","status",
                                             "result","outcome","state")
                                 if n in fields),None)
                if action_key:
                    info["action_counts"]=count_status(conn,name,action_key)
                # Include no row payloads, no user names, IDs or content.
            out[name]=info
        receipts=out.get("rg_news2_photo_dispatch",{}).get("receipts")
        out["canary_receipt_still_present"]=(
            receipts is not None and receipts>=BASELINE["post_canary_receipts"])
        out["callback_evidence"] = decision_evidence(out)
        return out
    finally:
        conn.close()

def decision_evidence(data):
    cand=data.get("rg_news2_photo_dispatch",{}).get("newest_photo_candidate",{})
    reviewed=cand.get("photo_reviewed") is True
    latest_status=cand.get("status")
    explicit=latest_status in ("rejected","approved","accepted","photo_reviewed","photo_rejected")
    audits=data.get("rg_v35_photo_audit",{})
    mod=data.get("moderation_dispatch",{})
    auditing=(audits.get("rows",0)>BASELINE["pre_button_photo_audit"] or
              mod.get("rows",0)>BASELINE["pre_button_moderation_dispatch"])
    # Never claim a button was processed solely from a general audit count,
    # whose added records may be unrelated to this newest photo.
    if cand.get("linked") and reviewed and (explicit or cand.get("review_note_present")):
        status="LATEST_CARD_REVIEW_STATE_CONFIRMED"
    elif cand.get("linked") and reviewed:
        status="LATEST_CARD_REVIEWED_DECISION_UNCLASSIFIED"
    elif auditing:
        status="ACTIVITY_FOUND_BUT_NOT_LINKED_TO_CLICKED_CARD"
    else:
        status="CALLBACK_NOT_CONFIRMED"
    return {"status":status, "last_photo_linked":cand.get("linked",False),
            "reviewed_flag_on_last_photo":reviewed,
            "new_audit_or_moderation_rows_since_pre_canary":auditing,
            "note":"A callback is confirmed only when the newest photo is linked to a reviewed candidate."}

def parse_sched(output):
    items={}
    current=None
    for line in output.splitlines():
        m=TASK_FIELD.match(line)
        if not m:continue
        name,val=m.groups();low=name.lower()
        val=val.strip().strip("[]")
        if low=="id":
            current=int(val) if val.isdigit() else None
            if current is not None:
                items[current]={"enabled":False,"status":"unknown",
                                "last_run":None,"command_matches":False}
        elif current is not None:
            item=items[current]
            if low=="state":item["enabled"]=val.lower()=="enabled"
            if low=="status":
                item["status"]=val.lower() if val.lower() in (
                    "success","failed","running","error","unknown") else "unknown"
            if low=="last run time":
                try:
                    item["last_run"]=datetime.datetime.strptime(val,
                                     "%a %b %d %H:%M:%S %Y")
                except ValueError:pass
            if low in ("command","name"):
                item["command_matches"]=item["command_matches"] or (
                    "rg_news_dsm_tick.sh" in val.lower())
    item=items.get(SCHED_TASK)
    if not item:
        return {"task_id":SCHED_TASK,"task_found":False,"live_execution":"UNVERIFIED"}
    dt=item.pop("last_run")
    if dt:
        age=(datetime.datetime.now()-dt).total_seconds()
        item["last_run_age_min"]=round(max(0,age)/60,1)
        item["recent_60min"]=-120<=age<=3600
    else:
        item["recent_60min"]=False
    item["task_id"]=SCHED_TASK
    item["task_found"]=True
    item["live_execution"]="RECENT_SCHEDULER_SUCCESS" if (
        item["enabled"] and item["status"]=="success" and
        item["recent_60min"] and item["command_matches"]) else "NOT_CONFIRMED"
    return item

def scheduler(tick,app):
    state={"hook_file_present":tick.is_file() and not tick.is_symlink()}
    if not state["hook_file_present"]:
        return dict(state,hook_installed=False,scheduled_run="UNVERIFIED")
    raw=tick.read_text(encoding="utf-8",errors="replace")
    state["hook_installed"]=TICK_MARK in raw
    state["single_hook_line"]=(raw.count("rg_news2_private_final_guard_v1.py")==1)
    state["legacy_preserved"]="rg_prior=$?" in raw and "if [ \"$rg_prior\" -ne 0 ]" in raw
    state["guard_file_present"]=(app/GUARD_NAME).is_file()
    try:
        p=subprocess.run(["/bin/sh","-n",str(tick)],
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=6)
        state["shell_syntax_ok"]=p.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        state["shell_syntax_ok"]=False
    cmd=next((p for p in ("/usr/syno/bin/synoschedtask",
                         "/usr/syno/sbin/synoschedtask") if os.path.isfile(p)),None)
    if cmd:
        try:
            p=subprocess.run([cmd,"--get"],stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,timeout=12)
            if p.returncode==0:
                out=p.stdout.decode("utf-8","replace")
                state["dsm_task"]=parse_sched(out)
            else:state["dsm_task"]={"task_id":SCHED_TASK,"task_found":False,
                                    "live_execution":"DSM_GET_FAILED"}
        except (OSError,subprocess.TimeoutExpired):
            state["dsm_task"]={"task_id":SCHED_TASK,"task_found":False,
                               "live_execution":"DSM_QUERY_FAILED"}
    else:
        state["dsm_task"]={"task_id":SCHED_TASK,"task_found":False,
                           "live_execution":"DSM_COMMAND_UNAVAILABLE"}
    state["scheduled_run"]="RECENT_SCHEDULER_SUCCESS" if (
        state["hook_installed"] and state["single_hook_line"] and
        state["legacy_preserved"] and state["shell_syntax_ok"] and
        state["guard_file_present"] and
        state["dsm_task"]["live_execution"]=="RECENT_SCHEDULER_SUCCESS"
        ) else "NOT_CONFIRMED"
    return state

def callback_state(app):
    callback=app/"operator/rg_news2_p31_guarded_callback_once.py"
    d={"installed_callback_source_unchanged":sha12(callback)==CALLBACK_HASH}
    probe=[]
    if app.is_dir():
        for parent,dirs,files in os.walk(str(app),followlinks=False):
            depth=len(pathlib.Path(parent).relative_to(app).parts)
            dirs[:]=[x for x in dirs if depth<3 and x not in (
                "backups","venv","secrets","cache") and not x.startswith(".")]
            for n in files:
                if n!="callback_v29_state.json":continue
                f=pathlib.Path(parent)/n
                if f.is_symlink() or not f.is_file():continue
                try:
                    stat=f.stat()
                    if stat.st_size>1024*1024:continue
                    age=time.time()-stat.st_mtime
                    probe.append({"fresh_last_15min":-120<=age<=900,
                                  "age_minutes":round(max(0,age)/60,1)})
                except OSError:pass
    d["callback_heartbeat_files"]=probe[:5]
    return d

def run(app=APP):
    data={"schema":"RG_NEWS2_POST_BUTTON_LIVE_VERIFY_V1",
          "time_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "readonly":True,"telegram_calls":0,"pollers_started":0,
          "publications":0,"database_writes":0,"baseline":BASELINE}
    data["sqlite"]=ledger(app/"news.sqlite3")
    data["moderator_callback"]=callback_state(app)
    data["synology_scheduler"]=scheduler(app/"rg_news_dsm_tick.sh",app)
    d=data["sqlite"].get("callback_evidence",{}).get("status","UNKNOWN")
    sc=data["synology_scheduler"]["scheduled_run"]
    data["verdict"]={
      "callback":d,
      "sqlite_decision_recorded":d=="LATEST_CARD_REVIEW_STATE_CONFIRMED",
      "scheduler":sc,
      "system_end_to_end_verified":(
           d=="LATEST_CARD_REVIEW_STATE_CONFIRMED" and
           sc=="RECENT_SCHEDULER_SUCCESS")
    }
    return data

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        (root/"operator").mkdir()
        db=root/"news.sqlite3"
        c=sqlite3.connect(str(db))
        c.execute("CREATE TABLE candidates(id INTEGER PRIMARY KEY,status TEXT,photo_reviewed INT,photo_review_note TEXT)")
        c.execute("INSERT INTO candidates VALUES (10,?,?,?)",
                  ("awaiting_moderation",1,"accepted"))
        c.execute("CREATE TABLE rg_news2_photo_dispatch(candidate_id INTEGER,telegram_message_id INTEGER)")
        c.executemany("INSERT INTO rg_news2_photo_dispatch VALUES(?,?)",
                      [(1,100),(2,101),(3,102),(10,103)])
        c.execute("CREATE TABLE rg_v35_photo_audit(action TEXT)")
        c.executemany("INSERT INTO rg_v35_photo_audit VALUES(?)",
                     [("queued",)]*4+[("accepted",)])
        c.execute("CREATE TABLE moderation_dispatch(state TEXT)")
        c.executemany("INSERT INTO moderation_dispatch VALUES(?)",
                      [("queued",)]*7)
        c.commit();c.close()
        x=ledger(db)
        assert x["callback_evidence"]["status"]=="LATEST_CARD_REVIEW_STATE_CONFIRMED"
        assert x["candidates"]["photo_reviewed_true"]==1
        assert x["rg_news2_photo_dispatch"]["receipts"]==4
        t=parse_sched("ID: [4]\nState: [enabled]\nStatus: [success]\n"
                      "Last Run Time: ["+datetime.datetime.now().strftime(
                           "%a %b %d %H:%M:%S %Y")+"]\n"
                      "Command: [/volume1/docker/RG_TELEGRAM_NEWS_2/rg_news_dsm_tick.sh]\n")
        assert t["live_execution"]=="RECENT_SCHEDULER_SUCCESS",t
        c=sqlite3.connect(str(db))
        c.execute("UPDATE candidates SET photo_reviewed=0, photo_review_note=NULL")
        c.commit();c.close()
        y=ledger(db)
        assert y["callback_evidence"]["status"]=="ACTIVITY_FOUND_BUT_NOT_LINKED_TO_CLICKED_CARD"
        text=json.dumps(x)
        for secret in ("100","101","102","103","10","accepted_for_testing_secret"):
            assert "accepted_for_testing_secret" not in text
    print("RG_NEWS2_POST_BUTTON_LIVE_VERIFY_V1_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(run(),indent=2,ensure_ascii=False,sort_keys=True))
    else:sys.exit("Only selftest or inspect supported")
