#!/usr/bin/env python3
"""Read-only Synology scheduler and MCP heartbeat preflight.

Reads only whitelisted heartbeat/status files, task filenames and process names.
Never executes task scripts, sends Telegram messages, exposes tokens or edits NAS.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

FILES = (
    "scheduler_last_check_at",
    "scheduler_last_check_status",
    "mcp_tick_heartbeat_at",
    "rg_resilience_heartbeat_at",
    "telegram_control_plane_last_sync_at",
    "telegram_scheduler_components_checked_at",
    "telegram_scheduler_components_status",
    "nas_command_bus_error",
    "scheduler_dispatch_error",
)
SCRIPTS = (
    "RG_NAS_SCHEDULER_TICK.sh",
    "RG_NAS_MCP_TICK.sh",
    "RG_NAS_MCP_GUARD.sh",
)
CRON_PATHS = (
    "/etc/crontab",
    "/usr/syno/etc/crontab",
    "/usr/syno/etc/synoschedtask.conf",
)
UTC = dt.timezone.utc

def read_status(file: pathlib.Path, now: dt.datetime) -> dict:
    try:
        meta = file.stat()
        value = file.read_text(encoding="utf-8", errors="replace")[:120].strip()
        # Whitelist plain numeric and known status symbols; never echo credentials.
        if file.name.endswith("_at") or "heartbeat" in file.name:
            try:
                timestamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("naive timestamp")
                seconds = int((now - timestamp.astimezone(UTC)).total_seconds())
                return {"exists": True, "age_seconds": seconds, "fresh_15m": -120 <= seconds <= 900}
            except ValueError:
                return {"exists": True, "mtime_age_sec": max(0, int(now.timestamp() - meta.st_mtime)), "timestamp_valid": False}
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,72}", value):
            return {"exists": True, "value": value}
        return {"exists": True, "value_redacted": True}
    except OSError:
        return {"exists": False}

def cron_match(path: pathlib.Path, target: str) -> dict:
    """Only publish counts and approximate active/inactive flags, not command text."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"accessible": False}
    found = [s.strip() for s in lines if target in s]
    return {
        "accessible": True,
        "matches": len(found),
        "noncomment_matches": sum(1 for s in found if not s.startswith("#") and not s.startswith(";")),
    }

def inspect(root: pathlib.Path, cron_paths=CRON_PATHS, now=None) -> dict:
    now = now or dt.datetime.now(UTC)
    state = root / "RG_NAS_STATE"
    scripts = {}
    for name in SCRIPTS:
        p = root / name
        try:
            st = p.stat()
            scripts[name] = {"exists": True, "bytes": st.st_size,
                             "mtime_age_sec": max(0, int(now.timestamp()-st.st_mtime)),
                             "symlink": p.is_symlink()}
        except OSError:
            scripts[name] = {"exists": False}
    tasks = {}
    for location in cron_paths:
        cp = pathlib.Path(location)
        tasks[str(cp)] = {}
        for name in SCRIPTS[:2]:
            tasks[str(cp)][name] = cron_match(cp, name)
    exe = shutil.which("docker")
    return {
        "schema": "RG_NAS_SCHEDULER_PREFLIGHT_V1",
        "read_only": True,
        "host_time_utc": now.isoformat(),
        "run_as_root": os.geteuid() == 0 if hasattr(os,"geteuid") else False,
        "python": sys.version.split()[0],
        "docker_cli_found": bool(exe),
        "state_dir_exists": state.is_dir(),
        "files": {name: read_status(state / name, now) for name in FILES},
        "scripts": scripts,
        "task_configs": tasks,
        "synology_scheduler_cli_exists": any(pathlib.Path(p).exists() for p in (
            "/usr/syno/bin/synoschedtask", "/usr/syno/sbin/synoschedtask")),
    }

def selftest() -> None:
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        root=pathlib.Path(td)
        state=root/"RG_NAS_STATE"
        state.mkdir()
        (state/"scheduler_last_check_status").write_text("OK")
        cron=root/"crontab"
        cron.write_text("#RG_NAS_MCP_TICK.sh\n*/5 * * * * root sh /foo/RG_NAS_SCHEDULER_TICK.sh --secret=NEVER_ECHO\n")
        out=inspect(root, cron_paths=(str(cron),))
        assert out["files"]["scheduler_last_check_status"]["value"]=="OK"
        assert out["task_configs"][str(cron)]["RG_NAS_SCHEDULER_TICK.sh"]["noncomment_matches"]==1
        assert out["task_configs"][str(cron)]["RG_NAS_MCP_TICK.sh"]["noncomment_matches"]==0
        assert "NEVER_ECHO" not in json.dumps(out)
        assert out["files"]["mcp_tick_heartbeat_at"]["exists"] is False
    print("RG_NAS_SCHEDULER_PREFLIGHT_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("diagnose","selftest"), default="diagnose")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("/volume1/docker"))
    args=parser.parse_args()
    if args.mode=="selftest":
        selftest()
    else:
        print(json.dumps(inspect(args.root), ensure_ascii=False, indent=2, sort_keys=True))
