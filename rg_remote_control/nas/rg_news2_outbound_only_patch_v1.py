#!/usr/bin/env python3
"""News2 v0.3: safely separate outbound card delivery from polling ownership.

Install a minimal patch after backing up rg_moderation.py. Does not open any
gate, poll, send a message, alter the database, or affect channel publishing.
"""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
TARGET = BASE / "rg_moderation.py"
OLD = """    cfg=config()
    if not OWNER.is_file() or OWNER.is_symlink(): raise ValueError('EXCLUSIVE_POLLING_OWNER_UNVERIFIED')
    row=claim_next()"""
NEW = """    cfg=config()
    # Outbound sendPhoto does not consume updates or compete for getUpdates.
    # The moderator delivery gate remains mandatory.
    # Exclusive polling ownership is still required inside poll_once().
    row=claim_next()"""

def main():
    if os.geteuid() != 0:
        raise RuntimeError("SUDO_REQUIRED")
    if not TARGET.is_file() or TARGET.is_symlink():
        raise RuntimeError("UNSAFE_TARGET")
    original = TARGET.read_text(encoding="utf-8")
    if original.count(OLD) != 1:
        raise RuntimeError("UNEXPECTED_SOURCE_ABORT")
    updated = original.replace(OLD, NEW, 1)
    if updated.count("if not OWNER.is_file() or OWNER.is_symlink(): raise ValueError('EXCLUSIVE_POLLING_OWNER_UNVERIFIED')") != 1:
        raise RuntimeError("POLL_OWNER_GUARD_MISSING")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = TARGET.with_name("rg_moderation.py.backup_" + stamp)
    if backup.exists():
        raise RuntimeError("BACKUP_EXISTS")
    backup.write_text(original, encoding="utf-8")
    os.chmod(str(backup), 0o600)
    tmp = TARGET.with_name(".rg_moderation.py.reviewed_new")
    if tmp.exists() or tmp.is_symlink():
        raise RuntimeError("TEMP_EXISTS")
    try:
        tmp.write_text(updated, encoding="utf-8")
        os.chmod(str(tmp), 0o644)
        subprocess.run([sys.executable, "-m", "py_compile", str(tmp)], check=True)
        os.replace(str(tmp), str(TARGET))
    finally:
        if tmp.exists():
            tmp.unlink()
    r = subprocess.run([sys.executable, str(TARGET), "selftest"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if r.returncode:
        os.replace(str(backup), str(TARGET))
        raise RuntimeError("SELFTEST_FAILED_RESTORED_BACKUP")
    print(json.dumps({"result":"PATCH_APPLIED_SELFTEST_PASS","backup":str(backup),"delivery_gate_opened":False,"owner_gate_opened":False,"poll_owner_guard_retained":True,"channel_sends":0,"telegram_calls":0},ensure_ascii=False))
if __name__=="__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"result":"BLOCKED","reason":str(e) if isinstance(e,RuntimeError) else type(e).__name__}))
        sys.exit(1)
