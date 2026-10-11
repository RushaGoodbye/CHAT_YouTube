#!/usr/bin/env python3
"""Install a fail-closed Telegram-only post-sync guard in NAS auto-deploy.
No Worker deployment, Cloudflare calls, or service restarts.
"""
import argparse, pathlib, shutil, subprocess, tempfile, os, json
from datetime import datetime, timezone
AUTODEPLOY=pathlib.Path("/volume1/docker/RG_NAS_AUTO_DEPLOY.sh")
GUARD=pathlib.Path("/volume1/docker/RG_TELEGRAM_STAGED_ALERTS_GUARD.py")
ANCHOR='sync_worker "$ALERT_SRC" "$ALERT_TARGET"'
INSERT='''sync_worker "$ALERT_SRC" "$ALERT_TARGET"
# Telegram-only post-sync guard. Fail closed before creating or starting deploy containers.
[ -f "$ROOT/RG_TELEGRAM_STAGED_ALERTS_GUARD.py" ] || fail "Telegram quota guard missing; refusing Alerts deploy"
python3 "$ROOT/RG_TELEGRAM_STAGED_ALERTS_GUARD.py" apply "$ALERT_TARGET/src/quota-entry.js" || fail "Telegram quota guard refused Alerts deploy"'''
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("mode",choices=["selftest","audit","apply"])
    ap.add_argument("--deploy",type=pathlib.Path,default=AUTODEPLOY)
    ap.add_argument("--guard",type=pathlib.Path,default=GUARD)
    a=ap.parse_args()
    if a.mode=="selftest":
        demo='sync_worker "$VIDEO_SRC" "$VIDEO_TARGET"\n'+ANCHOR+'\nsync_worker "$CONTENT_SRC" "$CONTENT_TARGET"'
        result=demo.replace(ANCHOR,INSERT,1)
        assert result.count(INSERT)==1 and result.count(ANCHOR)==1
        assert result.index(INSERT)<result.index('sync_worker "$CONTENT_SRC"')
        print('SELFTEST_PASS');return
    path=a.deploy
    if not path.is_file() or path.is_symlink() or path.stat().st_size>200000: raise SystemExit("BLOCKED: auto-deploy source invalid")
    before=path.read_text("utf-8")
    if INSERT in before:
        print(json.dumps({"status":"ALREADY_GUARDED","modifications":0}));return
    if before.count(ANCHOR)!=1 or 'sync_worker "$CONTENT_SRC" "$CONTENT_TARGET"' not in before:
        raise SystemExit("BLOCKED: unexpected deploy layout")
    after=before.replace(ANCHOR,INSERT,1)
    if after.index(INSERT)>after.index('sync_worker "$CONTENT_SRC" "$CONTENT_TARGET"'):
        raise SystemExit("BLOCKED: incorrect stage order")
    if a.mode=="audit":
        print(json.dumps({"status":"PATCH_READY","guard_will_run":"after_alert_source_sync","cloudflare_calls":0,"modifications":0}));return
    if not a.guard.is_file() or a.guard.is_symlink(): raise SystemExit("BLOCKED: staged guard not installed")
    syntax=subprocess.run(["sh","-n"],input=after,text=True,capture_output=True)
    if syntax.returncode: raise SystemExit("BLOCKED: shell syntax failed")
    backup=path.with_name(path.name+".backup-quota-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(path,backup)
    fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix=".rg-autodeploy-")
    try:
        with os.fdopen(fd,"w") as f: f.write(after)
        shutil.copymode(path,tmp)
        os.replace(tmp,path)
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)
    print(json.dumps({"status":"PATCHED","shell_syntax":"PASS","backup":str(backup),"cloudflare_calls":0,"deploy_triggered":False}))
if __name__=="__main__":main()
