#!/usr/bin/env python3
"""Telegram FREE quota pre-deploy gate. Read-only. Exit 0 only when guard is present."""
import json
import pathlib
import re
import sys

SOURCE = pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src/quota-entry.js")
CORE = "const core = worker.scheduled(event, optimizedEnv(env), ctx);"
WATCHDOG = "runDoModerationWatchdog(env)"
GUARD = "watchdogSlotMinute % 15 === 0"

def audit(text):
    core_count = text.count(CORE)
    guard_count = text.count(GUARD)
    call_count = text.count(WATCHDOG)
    # Restrict to scheduled method and ensure guard encloses the watchdog call.
    block = re.search(r"async scheduled\(event, env, ctx\)\s*\{(.+?)\n  \},\s*\n  async queue", text, re.S)
    valid = False
    if block:
        value = block.group(1)
        valid = bool(re.search(
            r"const core = worker\.scheduled\(event, optimizedEnv\(env\), ctx\);"
            r"[\s\S]*?if\s*\(watchdogSlotMinute\s*%\s*15\s*===\s*0\)\s*\{"
            r"\s*ctx\.waitUntil\(runDoModerationWatchdog\(env\)",
            value
        ))
    return {"core_present": core_count == 1,
            "watchdog_call_count": call_count,
            "guard_count": guard_count,
            "scheduled_guarded": valid,
            "safe_to_deploy": core_count == 1 and guard_count == 1 and valid}

def main():
    if "--selftest" in sys.argv:
        block = """async scheduled(event, env, ctx) {
    const core = worker.scheduled(event, optimizedEnv(env), ctx);
    const watchdogSlotMinute = Math.floor(Number(event?.scheduledTime || Date.now()) / 60000);
    if (watchdogSlotMinute % 15 === 0) {
      ctx.waitUntil(runDoModerationWatchdog(env).catch((error) => console.error(error)));
    }
    return core;
  },
  async queue"""
        assert audit(block)["safe_to_deploy"]
        assert not audit(block.replace("watchdogSlotMinute % 15 === 0","true"))["safe_to_deploy"]
        print(json.dumps({"selftest":"PASS","cloudflare_requests":0,"modifications":0}))
        return
    path = pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else SOURCE
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 500000:
        print(json.dumps({"status":"BLOCKED","reason":"worker_source_not_readable"}))
        sys.exit(2)
    result=audit(path.read_text(encoding="utf-8"))
    result["status"]="PASS" if result["safe_to_deploy"] else "BLOCKED"
    result["source"]=str(path)
    result["modifications"]=0
    print(json.dumps(result))
    sys.exit(0 if result["safe_to_deploy"] else 1)
if __name__=="__main__":
    main()
