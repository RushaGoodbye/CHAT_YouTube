#!/usr/bin/env python3
"""Safe Telegram DO watchdog quota guard. Default: audit only."""
import argparse, difflib, json, os, pathlib, shutil, subprocess, tempfile
from datetime import datetime, timezone
PATH=pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src/quota-entry.js")
OLD='    ctx.waitUntil(runDoModerationWatchdog(env).catch((error) => console.error("DO moderation watchdog failed:", error)));'
NEW='''    // FREE-tier guard: noncritical moderation watchdog once per 15 minutes.
    // Alert polling, minute of silence and moderation processing are untouched.
    const watchdogSlotMinute = Math.floor(Number(event?.scheduledTime || Date.now()) / 60000);
    if (watchdogSlotMinute % 15 === 0) {
      ctx.waitUntil(runDoModerationWatchdog(env).catch((error) => console.error("DO moderation watchdog failed:", error)));
    }'''
def patch(raw):
    if raw.count(OLD)!=1: raise ValueError("unexpected watchdog call count; refusing")
    for k in ("const core = worker.scheduled(event, optimizedEnv(env), ctx);","return core;","async scheduled(event, env, ctx)"):
        if k not in raw: raise ValueError("missing expected integration marker: "+k)
    return raw.replace(OLD,NEW,1)
def main():
    a=argparse.ArgumentParser()
    a.add_argument("mode",nargs="?",default="audit",choices=["audit","apply","selftest"])
    a.add_argument("--source",type=pathlib.Path,default=PATH)
    x=a.parse_args()
    if x.mode=="selftest":
        mock="async scheduled(event, env, ctx) {\nconst core = worker.scheduled(event, optimizedEnv(env), ctx);\n"+OLD+"\nreturn core;\n}"
        assert "watchdogSlotMinute % 15" in patch(mock)
        assert [m for m in range(60) if m%15==0]==[0,15,30,45]
        print(json.dumps({"selftest":"PASS","modifications":0,"cloudflare_requests":0}));return
    p=x.source
    if p.is_symlink() or not p.is_file() or p.stat().st_size>500000: raise SystemExit("FAIL_CLOSED: invalid source")
    old=p.read_text(encoding="utf-8")
    if NEW in old and OLD not in old: print('{"status":"ALREADY_PATCHED"}');return
    new=patch(old)
    if x.mode=="audit":
        print("".join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile="original",tofile="guarded")))
        print(json.dumps({"status":"PATCH_READY","modifications":0,"alert_poll":"unchanged"}));return
    if os.geteuid()!=0: raise SystemExit("FAIL_CLOSED: sudo required")
    with tempfile.TemporaryDirectory(prefix="rg-telegram-guard-") as d:
        candidate=pathlib.Path(d)/"candidate.mjs"
        candidate.write_text(new,encoding="utf-8")
        node=shutil.which("node")
        if node: subprocess.run([node,"--check",str(candidate)],check=True,timeout=15)
        backup=p.with_name(p.name+".backup-free-quota-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        shutil.copy2(p,backup)
        staged=p.with_name(p.name+".tmp-free-quota-guard")
        staged.write_text(new,encoding="utf-8")
        os.chmod(staged,p.stat().st_mode)
        os.replace(staged,p)
    print(json.dumps({"status":"SOURCE_PATCHED_NOT_DEPLOYED","backup":str(backup),"alert_poll":"unchanged","watchdog_every_minutes":15,"syntax_check":"PASS" if node else "NODE_UNAVAILABLE"}))
if __name__=="__main__": main()
