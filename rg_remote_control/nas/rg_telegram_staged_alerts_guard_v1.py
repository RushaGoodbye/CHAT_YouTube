#!/usr/bin/env python3
"""Fail-closed Telegram alert Worker staging guard. No Cloudflare/Telegram API calls."""
import argparse
import pathlib
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

OLD='    ctx.waitUntil(runDoModerationWatchdog(env).catch((error) => console.error("DO moderation watchdog failed:", error)));'
NEW='''    // Quota guard: watchdog every 15 minutes, alerts poll unchanged.
    const watchdogSlotMinute = Math.floor(Number(event?.scheduledTime || Date.now()) / 60000);
    if (watchdogSlotMinute % 15 === 0) {
      ctx.waitUntil(runDoModerationWatchdog(env).catch((error) => console.error("DO moderation watchdog failed:", error)));
    }'''
CORE='const core = worker.scheduled(event, optimizedEnv(env), ctx);'

def transform(raw):
    if raw.count(CORE)!=1:
        raise ValueError("ambiguous scheduled core")
    if raw.count("watchdogSlotMinute % 15 === 0")==1:
        start=raw.index("watchdogSlotMinute % 15 === 0")
        nearby=raw[start:start+300]
        if "ctx.waitUntil(runDoModerationWatchdog(env)" not in nearby:
            raise ValueError("existing guard does not enclose watchdog call")
        return raw, "ALREADY_GUARDED"
    if raw.count(OLD)!=1:
        raise ValueError("unexpected watchdog expression")
    candidate=raw.replace(OLD,NEW,1)
    if not (candidate.index(CORE)<candidate.index(NEW)<candidate.index("return core;",candidate.index(CORE))):
        raise ValueError("watchdog not immediately associated with scheduled handler")
    return candidate,"PATCH_READY"

def check_node(source):
    node=shutil.which("node")
    if not node:
        docker=shutil.which("docker")
        if not docker:
            raise ValueError("Node and Docker unavailable")
        inspect=subprocess.run([docker,"inspect","-f","{{.Config.Image}}","rg-alerts-deploy-deploy-1"],capture_output=True,text=True,timeout=10)
        if inspect.returncode or not inspect.stdout.strip():
            raise ValueError("Existing Alerts deploy image unavailable")
        image=inspect.stdout.strip()
        with tempfile.TemporaryDirectory() as d:
            temp=pathlib.Path(d)/"candidate.mjs"
            temp.write_text(source,"utf-8")
            subprocess.run([docker,"run","--rm","--network","none","--entrypoint","node","-v",d+":/rg-check:ro",image,"--check","/rg-check/candidate.mjs"],check=True,timeout=45,capture_output=True)
        return
    with tempfile.TemporaryDirectory() as d:
        temp=pathlib.Path(d)/"candidate.mjs"
        temp.write_text(source,"utf-8")
        subprocess.run([node,"--check",str(temp)],check=True,timeout=20,capture_output=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["selftest","audit","apply"])
    p.add_argument("file",nargs="?",default="/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src/quota-entry.js")
    args=p.parse_args()
    if args.mode=="selftest":
        mock=f'''export default {{
  async scheduled(event, env, ctx) {{
    {CORE}
{OLD}
    return core;
  }}
}};'''
        result,status=transform(mock)
        assert status=="PATCH_READY" and "watchdogSlotMinute % 15" in result
        assert transform(result)[1]=="ALREADY_GUARDED"
        print("SELFTEST_PASS")
        return
    path=pathlib.Path(args.file)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>500000:
        raise SystemExit("BLOCKED: missing or unsafe source")
    original=path.read_text("utf-8")
    try:
        updated,status=transform(original)
        check_node(updated)
    except (ValueError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as e:
        raise SystemExit(f"BLOCKED: {type(e).__name__}: {str(e)[:200]}")
    if args.mode=="audit":
        print(f"{status} NODE_SYNTAX_PASS no_changes=true")
        return
    if status=="ALREADY_GUARDED":
        print("ALREADY_GUARDED NODE_SYNTAX_PASS no_changes=true")
        return
    backup=path.with_name(path.name+".backup-staging-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(path,backup)
    fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix=".quota-guard-")
    try:
        import os
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            out.write(updated)
        shutil.copymode(path,tmp)
        os.replace(tmp,path)
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)
    print("STAGING_PATCHED NODE_SYNTAX_PASS backup="+str(backup))
if __name__=="__main__": main()
