#!/usr/bin/env python3
"""Read-only batch audit for ACTIVE RG NEWS2, not retired NAS/MCP scheduler.

No Bot API, Cloudflare, database writes, task invocation or service restarts.
Output deliberately omits raw commands, text, tokens, chat IDs and candidate content.
Python 3.8 compatible; executable via /usr/bin/python3 on Synology.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
from urllib.request import urlopen

SCRIPT = "rg_news_dsm_tick.sh"
TARGET = "RG_TELEGRAM_NEWS_2"
UTC = dt.timezone.utc
KNOWN_TASK_ID = 4
NAME_RE = re.compile(r"^\s*(ID|State|Status|Last Run Time|Name|Command):\s*(.*)$", re.I)
SAFE_NAME = re.compile(r"^[a-zA-Z0-9_.-]{1,96}$")
STATUS_WORDS = {"success", "failed", "running", "enabled", "disabled", "unknown", "error"}

def parse_dsm(text):
    rows = {}
    current = None
    for line in text.splitlines():
        match = NAME_RE.match(line)
        if not match:
            continue
        k, raw = match.groups()
        val = raw.strip().strip("[]")
        if k.lower() == "id":
            id_match = re.fullmatch(r"\d{1,7}", val)
            current = int(val) if id_match else None
            if current is not None:
                rows[current] = {"id": current, "status": "unknown", "state": "unknown",
                                 "last_run": None, "script_match": False}
        elif current is not None:
            item = rows[current]
            if k.lower() in ("status", "state"):
                item[k.lower()] = val.lower() if val.lower() in STATUS_WORDS else "unknown"
            elif k.lower() == "last run time":
                try:
                    item["last_run"] = dt.datetime.strptime(val, "%a %b %d %H:%M:%S %Y")
                except ValueError:
                    pass
            elif k.lower() in ("command", "name"):
                item["script_match"] = item["script_match"] or SCRIPT.lower() in val.lower()
    return rows

def safe_recent_files(root, limit=24):
    allowed = ("heartbeat", "health", "callback_v29", "tick", "scheduler", "status", "watchdog")
    bad = ("secret", "token", "credential", ".env", "session", "password")
    found = []
    if not root.is_dir():
        return found
    for parent, dirs, files in os.walk(str(root)):
        depth = len(pathlib.Path(parent).relative_to(root).parts)
        dirs[:] = [d for d in dirs if depth < 3 and not d.startswith(".")
                   and not any(word in d.lower() for word in ("backup", "cache", "secrets", "venv"))]
        for name in files:
            low = name.lower()
            if not SAFE_NAME.fullmatch(name) or any(x in low for x in bad):
                continue
            if not any(x in low for x in allowed):
                continue
            path = pathlib.Path(parent) / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                age = int(max(0, dt.datetime.now(UTC).timestamp() - path.stat().st_mtime))
                found.append((age, name))
            except OSError:
                pass
    return [{"filename": name, "age_sec": age} for age, name in sorted(found)[:limit]]

def callback_probe(root, now=None):
    now = now or dt.datetime.now(UTC)
    found = []
    for parent, dirs, files in os.walk(str(root)):
        depth = len(pathlib.Path(parent).relative_to(root).parts)
        dirs[:] = [d for d in dirs if depth < 3 and not d.startswith(".")
                   and d.lower() not in ("cache", "backups", "venv", "secrets")]
        if "callback_v29_state.json" not in files:
            continue
        p = pathlib.Path(parent) / "callback_v29_state.json"
        try:
            if p.is_symlink() or p.stat().st_size > 1048576:
                continue
            age = int((now.timestamp() - p.stat().st_mtime))
            with p.open(encoding="utf-8") as handle:
                data = json.load(handle)
            found.append({"age_sec": age, "fresh_5m": -120 <= age <= 300,
                          "json_valid": isinstance(data, dict)})
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            found.append({"json_valid": False, "fresh_5m": False})
    found.sort(key=lambda x:x.get("age_sec", 999999))
    return {"count":len(found), "most_recent":found[0] if found else None}

def sqlite_probe(root):
    databases = []
    for parent, dirs, files in os.walk(str(root)):
        depth = len(pathlib.Path(parent).relative_to(root).parts)
        dirs[:] = [d for d in dirs if depth < 3 and d.lower() not in ("backups","cache","secrets","venv")]
        for name in files:
            if not name.endswith((".sqlite",".sqlite3",".db")) or not SAFE_NAME.fullmatch(name):
                continue
            p=pathlib.Path(parent)/name
            if p.is_symlink():
                continue
            databases.append(p)
    results = []
    for db in databases[:4]:
        item = {"found":True,"read_only":True,"immutable_snapshot":True,"quick_check":"unavailable"}
        try:
            connection=sqlite3.connect(db.resolve().as_uri()+"?mode=ro&immutable=1", uri=True, timeout=2)
            try:
                connection.execute("PRAGMA query_only=ON")
                item["quick_check"]=connection.execute("PRAGMA quick_check(1)").fetchone()[0]
            finally:
                connection.close()
        except (sqlite3.Error, OSError, ValueError):
            pass
        results.append(item)
    return {"candidates":len(databases),"checked":results}

def run(root, cli_output=None, now=None):
    now=now or dt.datetime.now(UTC)
    state=root/"RG_NAS_STATE"
    news=root/TARGET
    tick=news/SCRIPT
    if cli_output is None:
        cmd=next((p for p in ("/usr/syno/bin/synoschedtask","/usr/syno/sbin/synoschedtask")
                  if pathlib.Path(p).is_file()),None)
        if cmd:
            try:
                cp=subprocess.run([cmd,"--get"],capture_output=True,text=True,timeout=12)
                cli_output=cp.stdout if cp.returncode==0 else ""
            except (OSError,subprocess.TimeoutExpired):
                cli_output=""
        else:
            cli_output=""
    records=parse_dsm(cli_output)
    task=records.get(KNOWN_TASK_ID)
    clock_age=None
    if task and task["last_run"]:
        clock_age=int((dt.datetime.now() - task["last_run"]).total_seconds()) if now is None else int((now.astimezone().replace(tzinfo=None) - task["last_run"]).total_seconds())
    syntax="missing"
    if tick.is_file() and not tick.is_symlink():
        try:
            result=subprocess.run(["/bin/sh","-n",str(tick)],capture_output=True,timeout=5)
            syntax="PASS" if result.returncode==0 else "FAIL"
        except (OSError,subprocess.TimeoutExpired):
            syntax="UNAVAILABLE"
    old={}
    for name in ("scheduler_last_check_at","mcp_tick_heartbeat_at"):
        path=state/name
        try:
            old[name]={"present":True,"mtime_age_sec":max(0,int(now.timestamp()-path.stat().st_mtime))}
        except OSError:
            old[name]={"present":False}
    cron={}
    try:
        content=pathlib.Path("/etc/crontab").read_text(encoding="utf-8",errors="replace")
        lines=[l for l in content.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        cron={"callback_v29_entries":sum("callback_v29" in line for line in lines),
              "news2_entries":sum(SCRIPT in line for line in lines)}
    except OSError:
        cron={"accessible":False}
    tick_summary={"found":tick.is_file(),"shell_syntax":syntax}
    if tick.is_file():
        tick_summary["mtime_age_sec"]=max(0,int(now.timestamp()-tick.stat().st_mtime))
    dsm={"id":KNOWN_TASK_ID,"found":bool(task)}
    if task:
        dsm.update({"enabled":task["state"]=="enabled", "last_result":task["status"],
                    "last_run_age_sec":clock_age, "script_match":task["script_match"]})
    callback=callback_probe(news,now)
    active=bool(task and task["state"]=="enabled" and task["status"]=="success"
                and clock_age is not None and -120<=clock_age<=900 and syntax=="PASS"
                and tick.is_file())
    # Task 4 being recently successful is scheduler evidence ONLY; not Telegram delivery proof.
    return {"schema":"RG_NEWS2_ACTIVE_BATCH_AUDIT_V1","read_only":True,
            "news2_dsm_task":dsm,"news2_tick_script":tick_summary,
            "callback_state":callback,"cron_counts":cron,
            "sqlite":sqlite_probe(news),"recent_monitor_files":safe_recent_files(news),
            "legacy_heartbeat_files":old,
            "old_autodeploy_task3_preserve_disabled":True,
            "public_channel_publish_status":"NOT_TESTED_NOT_CHANGED",
            "no_second_poller_invoked_by_audit":True,"telegram_api_calls":0,"database_writes":0,
            "task4_recent_execution_confirmed":active,
            "next_step":("monitor_REAL_NEWS2_callback_and_tick_without_reenabling_legacy"
                         if active else "inspect_TASK4_live_status_or_script_before_modification")}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        folder=root/TARGET
        folder.mkdir()
        (root/"RG_NAS_STATE").mkdir()
        (folder/SCRIPT).write_text("#!/bin/sh\nexit 0\n",encoding="utf-8")
        now=dt.datetime.now(UTC)
        stamp=now.astimezone().strftime("%a %b %d %H:%M:%S %Y")
        fixture="\n".join(("ID: [4]","Name: [RG NEWS2]","State: [enabled]",
                           "Status: [success]","Last Run Time: ["+stamp+"]",
                           "Command: [sh /volume1/docker/RG_TELEGRAM_NEWS_2/rg_news_dsm_tick.sh]"))
        (folder/"callback_v29_state.json").write_text('{"ok":true}',encoding="utf-8")
        report=run(root,cli_output=fixture,now=now)
        assert report["task4_recent_execution_confirmed"] is True
        assert report["callback_state"]["most_recent"]["fresh_5m"] is True
        assert report["public_channel_publish_status"]=="NOT_TESTED_NOT_CHANGED"
        assert report["no_second_poller_invoked_by_audit"] is True
        assert not report["news2_dsm_task"].get("command")
        assert report["old_autodeploy_task3_preserve_disabled"] is True
        assert report["sqlite"]["candidates"] == 0
    print("RG_NEWS2_ACTIVE_BATCH_AUDIT_SELFTEST_PASS")

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("mode",nargs="?",choices=("diagnose","selftest"),default="diagnose")
    args=cli.parse_args()
    if args.mode=="selftest":
        selftest()
    else:
        print(json.dumps(run(pathlib.Path("/volume1/docker")),ensure_ascii=False,sort_keys=True,indent=2))
