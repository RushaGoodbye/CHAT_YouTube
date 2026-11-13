#!/bin/sh
# One package for real NAS: audit + protected backup. No Telegram send or scheduler changes.
set -eu
umask 077
PY=/usr/bin/python3
AUDIT=/tmp/rg_news2_photo_repair_bundle_v1.py
BACKUP=/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots
[ "$(id -u)" -eq 0 ] || { echo 'ROOT_REQUIRED' >&2; exit 2; }
[ -f "$AUDIT" ] || { echo 'VERIFIED_AUDIT_FILE_MISSING' >&2; exit 2; }
[ -d /volume1/docker/RG_NAS_MONITOR ] || { echo 'GATUS_MONITOR_HOME_MISSING' >&2; exit 2; }
$PY -B "$AUDIT" selftest
$PY -B "$AUDIT" diagnose
echo '=== SAFE_BACKUP_AND_ROLLBACK_PREPARATION ==='
$PY -B - "$AUDIT" "$BACKUP" <<'PY'
import importlib.util
import json
import os
import pathlib
import stat
import sys
path=pathlib.Path(sys.argv[1])
directory=pathlib.Path(sys.argv[2])
if directory.is_symlink():
    raise SystemExit("SAFE_ABORT_BACKUP_PARENT_SYMLINK")
if directory.exists() and (stat.S_IMODE(directory.stat().st_mode) & 0o077):
    raise SystemExit("SAFE_ABORT_BACKUP_PERMISSIONS")
if not directory.exists():
    directory.mkdir(parents=False,mode=0o700)
spec=importlib.util.spec_from_file_location("news2_recovery_audit",str(path))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
result=mod.prepare(target_parent=directory)
print(json.dumps({
    "backup":result.get("backup"),
    "photo_dispatch_states":result["outbox"].get("status_counts",{}),
    "receipt_counts":result["outbox"].get("receipt_nonnull_count",{}),
    "outstanding_resend_blocked":result["remediation"]["active_queue_resend_blocked"],
    "live_scheduler_unchanged":not result["remediation"]["live_hook_changed"],
    "public_delivery_unchanged":result["remediation"]["public_channel_remains_disabled"],
    "second_poller_started":result["remediation"]["second_poller_started"],
},sort_keys=True,indent=2))
PY
echo 'RG_NEWS2_PHOTO_PREPARE_PACKAGE=COMPLETE_NO_LIVE_CHANGES'
