#!/usr/bin/env python3
"""Install/remove News2 outbound queue schedule; NO inbound polling or channel posts.
Daily unattended dispatch capped at 3 pending cards; launches one per 5 minutes.
"""
import os,pathlib,subprocess,sys,json,shlex,tempfile
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
OP=ROOT/"operator"
SCRIPT=OP/"outbound_tick.sh"
CRON=pathlib.Path("/etc/cron.d/rg_news2_outbound")
CONTENT="""#!/bin/sh
set -eu
BASE=/volume1/docker/RG_TELEGRAM_NEWS_2
test -f "$BASE/MODERATION_DELIVERY_ENABLED" || exit 0
test ! -e "$BASE/PUBLISH_ENABLED" || exit 0
test ! -e /volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled || exit 0
test -f /volume1/docker/RG_TELEGRAM_NEWS_2/operator/rg_news2_outbound_queue_v2.py || exit 0
/usr/bin/python3 /volume1/docker/RG_TELEGRAM_NEWS_2/operator/rg_news2_outbound_queue_v2.py tick
"""
# Synology cron.d may not be supported; prefer explicit /etc/crontab line only when verified.
def out(**x):print(json.dumps(x,ensure_ascii=False))
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ("stage","status"):raise RuntimeError("USAGE_STAGE_OR_STATUS")
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if OP.is_symlink():raise RuntimeError("OP_SYMLINK")
 if not ROOT.is_dir():raise RuntimeError("NEWS2_MISSING")
 if sys.argv[1]=="status":
  out(status="NEWS2_AUTOMATION_STAGE_STATUS",runner_present=SCRIPT.is_file(),automation_enabled=False,owner_proven=(ROOT/"NAS_EXCLUSIVE_OWNER_VERIFIED").exists())
  return
 if not OP.is_dir():raise RuntimeError("OP_MISSING")
 if SCRIPT.exists() and SCRIPT.is_symlink():raise RuntimeError("SCRIPT_SYMLINK")
 p=subprocess.run(["/bin/sh","-n"],input=CONTENT,universal_newlines=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if p.returncode:raise RuntimeError("SHELL_SYNTAX")
 source=pathlib.Path("/tmp/rg_news2_queue_v2.py")
 target=OP/"rg_news2_outbound_queue_v2.py"
 if not source.is_file() or source.is_symlink():raise RuntimeError("QUEUE_V2_NOT_IN_TMP")
 data=source.read_bytes()
 if b"QUEUE_V2_STATUS" not in data or b"m.send_one()" not in data or b"telegram_polls=0" not in data:raise RuntimeError("UNRECOGNIZED_QUEUE_VERSION")
 if target.is_symlink():raise RuntimeError("QUEUE_TARGET_SYMLINK")
 target.write_bytes(data)
 os.chmod(str(target),0o600)
 SCRIPT.write_text(CONTENT,encoding="utf-8")
 os.chmod(str(SCRIPT),0o700)
 out(status="OUTBOUND_AUTOMATION_STAGED",runner=str(SCRIPT),cron_installed=False,channel_sends=0,telegram_polls=0,next="Schedule only after operator confirms desired cadence")
if __name__=="__main__":
 try:main()
 except Exception as e:out(status="BLOCKED",reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__);sys.exit(1)
