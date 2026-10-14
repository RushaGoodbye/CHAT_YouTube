#!/usr/bin/env python3
"""Stage-only NAS runner for RG Telegram News 2.0 moderation.

Commands: preflight | stage | status
No Telegram API calls, cron modification, bot start, gate opening or DB writes.
Production activation requires separate exclusive getUpdates proof.
Python 3.7+ compatible.
"""
import datetime
import json
import os
import pathlib
import shutil
import sqlite3
import sys

BASE = pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
STATE = BASE / "operator"
MOD = BASE / "rg_moderation.py"
DB = BASE / "news.sqlite3"
LEGACY_GATE = pathlib.Path("/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled")
OWNER = BASE / "NAS_EXCLUSIVE_OWNER_VERIFIED"
DELIVERY = BASE / "MODERATION_DELIVERY_ENABLED"
SCRIPT = """#!/bin/sh
# Staged only; must not schedule until exclusive Telegram update ownership is proven.
set -eu
BASE=/volume1/docker/RG_TELEGRAM_NEWS_2
test -f "$BASE/NAS_EXCLUSIVE_OWNER_VERIFIED" || exit 20
test -f "$BASE/MODERATION_DELIVERY_ENABLED" || exit 21
test ! -e /volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled || exit 22
LOCK="$BASE/operator/moderation_tick.lock"
if ! mkdir "$LOCK" 2>/dev/null; then exit 23; fi
trap 'rmdir "$LOCK"' EXIT HUP INT TERM
python3 "$BASE/rg_moderation.py" poll-once
python3 "$BASE/rg_moderation.py" send-one
"""

def report():
    states = {}
    for name, path in (
        ("database", DB), ("moderation_module", MOD),
        ("moderation_config", BASE / "moderation.json"),
        ("owner_gate", OWNER), ("delivery_gate", DELIVERY),
        ("legacy_native_bot_gate", LEGACY_GATE),
        ("publisher_gate", BASE / "PUBLISH_ENABLED"),
    ):
        states[name] = path.is_file() and not path.is_symlink()
    result = {
        "schema": "RG_NEWS2_MODERATION_STAGE_V1",
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "files": states,
        "ready_to_activate": False,
        "exclusive_poll_owner_proven": False,
        "publication_disabled_by_this_tool": True,
        "no_telegram_calls": True,
        "no_news_db_writes": True,
    }
    if states["database"]:
        try:
            with sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True, timeout=4) as db:
                result["queue"] = dict(db.execute("SELECT status, count(*) FROM candidates GROUP BY status"))
        except (sqlite3.Error, OSError) as exc:
            result["database_check"] = type(exc).__name__
    return result

def preflight():
    r = report()
    errors = []
    if os.geteuid() != 0:
        errors.append("SUDO_REQUIRED")
    for key in ("database", "moderation_module", "moderation_config"):
        if not r["files"][key]:
            errors.append("MISSING_" + key.upper())
    if r["files"]["legacy_native_bot_gate"]:
        errors.append("LEGACY_NATIVE_BOT_GATE_PRESENT")
    if r["files"]["owner_gate"] or r["files"]["delivery_gate"]:
        errors.append("PREEXISTING_NEWS2_ACTIVATION_GATES_REQUIRE_REVIEW")
    r["preflight"] = "PASS_STAGE_ONLY" if not errors else "BLOCKED"
    r["issues"] = errors
    return r

def stage():
    r = preflight()
    if r["issues"]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 2
    if STATE.is_symlink():
        raise RuntimeError("OPERATOR_SYMLINK_REFUSED")
    STATE.mkdir(mode=0o700, exist_ok=True)
    os.chmod(str(STATE), 0o700)
    dest = STATE / "moderation_tick.sh"
    if dest.is_symlink():
        raise RuntimeError("RUNNER_SYMLINK_REFUSED")
    if dest.exists():
        old = dest.read_text(encoding="utf-8")
        if old != SCRIPT:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = STATE / ("moderation_tick." + stamp + ".bak")
            if backup.exists():
                raise RuntimeError("BACKUP_COLLISION")
            shutil.copy2(str(dest), str(backup))
            os.chmod(str(backup), 0o600)
    import tempfile
    handle, tmp = tempfile.mkstemp(prefix=".runner_", dir=str(STATE))
    try:
        with os.fdopen(handle, "w") as fp:
            fp.write(SCRIPT)
        os.chmod(tmp, 0o700)
        os.replace(tmp, str(dest))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    r["stage"] = "STAGED_NOT_ENABLED"
    r["runner"] = str(dest)
    r["cron_modified"] = False
    r["gates_changed"] = False
    r["telegram_messages_sent"] = 0
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("preflight", "stage", "status"):
        print("Usage: news2_moderation_stage_v1.py preflight|stage|status", file=sys.stderr)
        return 2
    if sys.argv[1] == "stage":
        return stage()
    r = preflight() if sys.argv[1] == "preflight" else report()
    r["stage_file_present"] = (STATE / "moderation_tick.sh").is_file()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"result":"BLOCKED","error_class":type(exc).__name__}))
        sys.exit(1)
