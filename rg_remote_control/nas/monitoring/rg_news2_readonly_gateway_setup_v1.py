#!/usr/bin/env python3
"""Install a passwordless, exact-command NEWS2 read-only audit via sudoers.

One-time interactive sudo needed. This installer has NO Telegram side effects,
NO blanket root/shell grant, and fails closed if existing files differ.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

STAGED = Path('/tmp/rg_news2_privileged_readonly_gateway_v1.py')
OPERATOR = Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
TARGET = OPERATOR/STAGED.name
DROP = Path('/etc/sudoers.d/rg-news2-readonly')
SUDOERS = Path('/etc/sudoers')
SOURCE_SHA = 'c3818f5a7634f1d6d2e6987a456c67e3b42fb115'
USER = 'Alex Los'
RULE = 'Alex\\ Los ALL=(root) NOPASSWD: /usr/bin/python3 '+str(TARGET)+' audit\n'

class Stop(ValueError):pass

def blob(b):
    return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()

def put(path,data,mode):
    fd,tmp=tempfile.mkstemp(prefix='.rg_news2_ro_',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def check():
    if os.geteuid()!=0:raise Stop('SUDO_REQUIRED')
    if not OPERATOR.is_dir() or OPERATOR.is_symlink():raise Stop('OPERATOR_UNSAFE')
    if OPERATOR.stat().st_mode & 0o022:raise Stop('OPERATOR_WRITABLE_BY_OTHERS')
    if not DROP.parent.is_dir() or DROP.parent.is_symlink():raise Stop('SUDOERS_D_UNSAFE')
    if not SUDOERS.is_file() or SUDOERS.is_symlink():raise Stop('SUDOERS_UNSAFE')
    text=SUDOERS.read_text()
    if not any(re.match(r'^\s*[@#]includedir\s+/etc/sudoers\.d\s*$', line) for line in text.splitlines()):
        raise Stop('SUDOERS_INCLUDE_NOT_CONFIRMED')
    if STAGED.is_symlink() or not STAGED.is_file() or STAGED.stat().st_size>100000:raise Stop('STAGED_GATEWAY_UNSAFE')
    data=STAGED.read_bytes()
    if blob(data)!=SOURCE_SHA:raise Stop('GATEWAY_BLOB_MISMATCH')
    test=subprocess.run(['/usr/bin/python3',str(STAGED),'selftest'],capture_output=True,text=True,timeout=10)
    if test.returncode or 'NEWS2_PRIVILEGED_READONLY_GATEWAY_SELFTEST_PASS' not in test.stdout:
        raise Stop('GATEWAY_SELFTEST_FAILED')
    if TARGET.exists() or TARGET.is_symlink():
        if TARGET.is_symlink() or TARGET.read_bytes()!=data or TARGET.stat().st_uid!=0:
            raise Stop('EXISTING_GATEWAY_DIFFERS')
    if DROP.exists() or DROP.is_symlink():
        if DROP.is_symlink() or DROP.read_text()!=RULE or DROP.stat().st_uid!=0:
            raise Stop('EXISTING_POLICY_DIFFERS')
    return data

def install():
    data=check()
    added_target=not TARGET.exists()
    added_policy=not DROP.exists()
    try:
        if added_target:put(TARGET,data,0o700)
        else:os.chmod(TARGET,0o700)
        if added_policy:put(DROP,RULE.encode('utf8'),0o440)
        else:os.chmod(DROP,0o440)
        visudo=shutil.which('visudo')
        if visudo:
            res=subprocess.run([visudo,'-c','-f',str(DROP)],capture_output=True,text=True,timeout=12)
            if res.returncode:raise Stop('SUDOERS_VALIDATION_FAILED')
        res=subprocess.run(['/usr/bin/sudo','-n','-l','-U',USER],
                           capture_output=True,text=True,timeout=12)
        if res.returncode or str(TARGET) not in res.stdout:
            raise Stop('SUDOERS_POLICY_NOT_EFFECTIVE')
        print('NEWS2_READONLY_GATEWAY_INSTALLED')
        print('PASSWORDLESS_EXACT_COMMAND_ONLY')
        print('/usr/bin/sudo -n /usr/bin/python3 '+str(TARGET)+' audit')
        return 0
    except Exception:
        if added_policy and DROP.is_file() and not DROP.is_symlink():DROP.unlink()
        if added_target and TARGET.is_file() and not TARGET.is_symlink():TARGET.unlink()
        raise

def selftest():
    assert RULE.startswith('Alex\\ Los ALL=(root) NOPASSWD: /usr/bin/python3 ')
    assert RULE.rstrip().endswith(' audit')
    assert ' ALL=(ALL) ALL' not in RULE
    assert '*' not in RULE
    print('NEWS2_SUDOERS_EXACT_READONLY_POLICY_SELFTEST_PASS')

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('mode',choices=['selftest','preflight','install'])
    args=a.parse_args()
    try:
        if args.mode=='selftest':selftest()
        elif args.mode=='preflight':check();print('NEWS2_SUDOERS_PREFLIGHT_PASS')
        else:install()
    except (Stop,OSError,ValueError,subprocess.TimeoutExpired) as e:
        print('NEWS2_SUDOERS_SAFE_STOP_'+type(e).__name__+': '+str(e)[:100])
        raise SystemExit(2)
