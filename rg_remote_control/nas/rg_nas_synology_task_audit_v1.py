#!/usr/bin/env python3
"""Read-only Synology task inventory. Never display task commands or secrets."""
import argparse
import base64
import glob
import json
import os
import pathlib
import re
import subprocess

TARGETS = ("RG_NAS_SCHEDULER_TICK.sh", "RG_NAS_MCP_TICK.sh",
           "RG_NAS_MCP_GUARD.sh", "RG_TELEGRAM_CONTROL_AGENT.sh")
# Script basenames only; never return raw DSM task content or arguments.
RG_SCRIPT_PATTERN = re.compile(r"\bRG_[A-Za-z0-9_-]{2,90}\.(?:sh|py)\b", re.I)
SCHEDULE_KEYS = ("type", "run hour", "run min", "repeat min", "repeat hour",
                 "can run task same time")
def script_refs(source):
    return sorted(set(RG_SCRIPT_PATTERN.findall(source)))
def schedule_fields(fields):
    return {key.replace(" ", "_"): fields[key] for key in SCHEDULE_KEYS
            if key in fields and re.fullmatch(r"[a-zA-Z0-9_-]{1,16}", fields[key])}

def targets(text):
    return [t for t in TARGETS if t.casefold() in text.casefold()]

def state(text):
    value = str(text).strip().strip("[]").lower()
    return value if value in ("enabled", "disabled", "running", "success", "failed", "error") else "unknown"

def cli_parse(source):
    entries = []
    current = None
    for line in source.splitlines():
        m = re.match(r"^\s*ID:\s*\[(\d+)\]", line, re.I)
        if m:
            if current and (current["targets"] or current["rg_named"]):
                entries.append(current)
            current = {"id": int(m.group(1)), "state": "unknown", "last_result": "unknown",
                       "targets": [], "script_refs": [], "rg_named": False}
            continue
        if current is None:
            continue
        match = re.match(r"^\s*(Name|State|Status|Command|Action):\s*(.*)$", line, re.I)
        if not match:
            continue
        kind, val = match.group(1).lower(), match.group(2).strip().strip("[]")
        if kind == "state":
            current["state"] = state(val)
        elif kind == "status":
            current["last_result"] = state(val)
        else:
            current["targets"] = sorted(set(current["targets"] + targets(val)))
            current["script_refs"] = sorted(set(current["script_refs"] + script_refs(val)))
            if kind == "name" and re.search("RG|NAS|MCP|TELEGRAM", val, re.I):
                current["rg_named"] = True
    if current and (current["targets"] or current["rg_named"]):
        entries.append(current)
    return entries

def task_parse(path, source):
    values = {}
    for line in source.splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            if key.strip() in ("id", "state", "name", "cmd", "action", "app args") + SCHEDULE_KEYS:
                values[key.strip()] = val.strip()
    texts = [values.get(k,"") for k in ("name", "action", "app args")]
    encoded = values.get("cmd","")
    if encoded and len(encoded) < 180000:
        try:
            texts.append(base64.b64decode(encoded, validate=True).decode("utf-8", "replace"))
        except (ValueError, UnicodeError):
            pass
    matched = targets("\n".join(texts))
    named = bool(re.search("RG|NAS|MCP|TELEGRAM", values.get("name",""), re.I))
    if not matched and not named:
        return None
    raw_id = values.get("id","")
    try:
        task_id = int(raw_id)
    except ValueError:
        found = re.search(r"(\d+)\.task$", path)
        task_id = int(found.group(1)) if found else -1
    return {"id": task_id, "state": state(values.get("state","")),
            "targets": matched, "rg_named": named,
            "script_refs": script_refs("\n".join(texts)),
            "cmd_decoded": bool(encoded),
            "schedule": schedule_fields(values)}

def audit(task_root="/usr/syno/etc/synoschedule.d", cron="/etc/crontab", sched_bin=None):
    binary = sched_bin or next((x for x in ("/usr/syno/bin/synoschedtask",
                                            "/usr/syno/sbin/synoschedtask") if os.path.isfile(x)), None)
    cli = {"available": bool(binary), "related_tasks": [], "error": None}
    if binary:
        try:
            result = subprocess.run([binary, "--get"], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, timeout=15)
            if result.returncode == 0:
                cli["related_tasks"] = cli_parse(result.stdout)
            else:
                cli["error"] = "get_failed"
                cli["exit_code"] = result.returncode
        except (OSError, subprocess.TimeoutExpired):
            cli["error"] = "get_unavailable"
    else:
        cli["error"] = "binary_missing"
    matching_files = []
    if os.path.isdir(task_root):
        for path in sorted(glob.glob(os.path.join(task_root, "*", "*.task")))[:1024]:
            try:
                if os.path.islink(path) or os.path.getsize(path) > 180000:
                    continue
                with open(path, encoding="utf-8", errors="replace") as handle:
                    entry = task_parse(path, handle.read())
                if entry:
                    matching_files.append(entry)
            except OSError:
                pass
    cron_ids = []
    try:
        with open(cron, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lstrip().startswith("#"):
                    continue
                match = re.search(r"\bsynoschedtask\s+--run\s+id=(\d+)\b", line)
                if match:
                    cron_ids.append(int(match.group(1)))
        cron_available = True
    except OSError:
        cron_available = False
    return {"schema":"RG_SYNOLOGY_TASK_AUDIT_V1", "read_only": True,
            "synology_cli": cli, "task_directory_available": os.path.isdir(task_root),
            "matching_task_files": matching_files, "cron_available":cron_available,
            "active_synoschedtask_cron_ids":sorted(set(cron_ids)),
            "target_scripts_present": {x: pathlib.Path("/volume1/docker", x).is_file() for x in TARGETS}}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        root=pathlib.Path(folder)
        (root/"tasks"/"root").mkdir(parents=True)
        cmd="sh /volume1/docker/RG_NAS_SCHEDULER_TICK.sh --password=SECRET_VALUE"
        task="id=18\nstate=disabled\nname=RG NAS Scheduler\ncmd="+base64.b64encode(cmd.encode()).decode()+"\n"
        (root/"tasks"/"root"/"18.task").write_text(task)
        (root/"crontab").write_text("*/5 * * * * root /usr/syno/bin/synoschedtask --run id=18\n")
        # Synology can mount /tmp with noexec; test the parser directly.
        # The live diagnose path still invokes the read-only --get command.
        fixture = "\n".join((
            "ID: [18]", "Name: [RG NAS Scheduler]", "State: [disabled]",
            "Command: [sh /volume1/docker/RG_NAS_SCHEDULER_TICK.sh --password=SECRET_VALUE]",
            "Status: [Failed]",
        ))
        parsed = cli_parse(fixture)
        assert len(parsed) == 1
        assert parsed[0]["id"] == 18
        assert parsed[0]["state"] == "disabled"
        assert parsed[0]["last_result"] == "failed"
        assert "SECRET_VALUE" not in json.dumps(parsed)
        result = audit(str(root/"tasks"), str(root/"crontab"), sched_bin="/absent/no-such-synoschedtask")
        assert result["active_synoschedtask_cron_ids"] == [18]
        assert result["matching_task_files"][0]["state"] == "disabled"
        assert result["matching_task_files"][0]["script_refs"] == ["RG_NAS_SCHEDULER_TICK.sh"]
        assert parsed[0]["script_refs"] == ["RG_NAS_SCHEDULER_TICK.sh"]
        assert "SECRET_VALUE" not in json.dumps(result)
    print("RG_SYNOLOGY_TASK_AUDIT_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("selftest","diagnose"), default="diagnose")
    args=parser.parse_args()
    if args.mode == "selftest":
        selftest()
    else:
        print(json.dumps(audit(), ensure_ascii=False, indent=2))
