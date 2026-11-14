#!/usr/bin/env python3
"""One-time, root-authorized, fail-closed installation of a NEWS2 read-only reconciler.

Adds ONE exact sudo command. No wildcard, no password exposure, no bot calls,
no publisher modifications, no general remote code execution.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SOURCE=Path('/tmp/rg_news2_decisions_reconcile_readonly_v1.py')
TARGET=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator/rg_news2_decisions_reconcile_readonly_v1.py')
POLICY=Path('/etc/sudoers.d/rg-news2-reconcile-ro')
USER='Alex Los'
EXPECTED_BLOB='dummypinned'
RULE='Alex\\ Los ALL=(root) NOPASSWD: /usr/bin/python3 '+str(TARGET)+' inspect\n'

class SafeStop(ValueError):pass

def gitblob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

def safe_write(path,raw,mode):
    fd,tmp=tempfile.mkstemp(prefix='.rg_news2_reconcile_',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode)
            f.write(raw)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def check():
    if os.geteuid()!=0:raise SafeStop('ROOT_REQUIRED')
    op=TARGET.parent
    if op.is_symlink() or not op.is_dir() or op.stat().st_uid!=0 or op.stat().st_mode&0o022:
        raise SafeStop('OPERATOR_OWNER_OR_PERMISSIONS_UNSAFE')
    if POLICY.parent.is_symlink() or not POLICY.parent.is_dir():
        raise SafeStop('POLICY_PARENT_UNSAFE')
    if not SOURCE.is_file() or SOURCE.is_symlink() or SOURCE.stat().st_size>60000:
        raise SafeStop('STAGED_SCRIPT_MISSING_OR_UNSAFE')
    raw=SOURCE.read_bytes()
    if gitblob(raw)!=EXPECTED_BLOB:raise SafeStop('PINNED_SCRIPT_HASH_MISMATCH')
    checkrun=subprocess.run(['/usr/bin/python3',str(SOURCE),'selftest'],
        capture_output=True,text=True,timeout=10)
    if checkrun.returncode or 'NEWS2_DECISION_RECONCILIATION_SELFTEST_PASS' not in checkrun.stdout:
        raise SafeStop('RECONCILER_SELFTEST_FAILED')
    if TARGET.exists() or TARGET.is_symlink():
        if TARGET.is_symlink() or TARGET.stat().st_uid!=0 or TARGET.read_bytes()!=raw:
            raise SafeStop('EXISTING_SCRIPT_DRIFT')
    if POLICY.exists() or POLICY.is_symlink():
        if POLICY.is_symlink() or POLICY.stat().st_uid!=0 or POLICY.read_bytes()!=RULE.encode():
            raise SafeStop('EXISTING_POLICY_DRIFT')
    return raw

def install():
    raw=check()
    new_target=not TARGET.exists()
    new_policy=not POLICY.exists()
    try:
        if new_target:safe_write(TARGET,raw,0o700)
        if new_policy:safe_write(POLICY,RULE.encode(),0o440)
        # Verify the effective authorization, which is necessary on DSM.
        probe=subprocess.run(['/usr/bin/sudo','-n','-l','-U',USER],
             capture_output=True,text=True,timeout=12)
        if probe.returncode or str(TARGET)+' inspect' not in probe.stdout:
            raise SafeStop('POLICY_NOT_EFFECTIVE')
        print('NEWS2_RECONCILER_READONLY_ACCESS_INSTALLED')
        print('EXACT_READONLY_COMMAND_ONLY')
    except Exception:
        if new_policy and POLICY.is_file() and not POLICY.is_symlink():POLICY.unlink()
        if new_target and TARGET.is_file() and not TARGET.is_symlink():TARGET.unlink()
        raise

def selftest():
    assert RULE.startswith('Alex\\ Los ALL=(root) NOPASSWD: /usr/bin/python3 ')
    assert RULE.endswith(' inspect\n') and '*' not in RULE
    assert '/tmp/' not in RULE
    print('NEWS2_RECONCILER_POLICY_SELFTEST_PASS')

if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:selftest()
        elif sys.argv[1:]==['preflight']:check();print('NEWS2_RECONCILER_ACCESS_PREFLIGHT_PASS')
        elif sys.argv[1:]==['install']:install()
        else:raise SafeStop('UNSUPPORTED_ACTION')
    except (SafeStop, OSError, subprocess.TimeoutExpired) as exc:
        print('NEWS2_RECONCILER_SAFE_STOP_'+str(exc)[:100]);raise SystemExit(2)
