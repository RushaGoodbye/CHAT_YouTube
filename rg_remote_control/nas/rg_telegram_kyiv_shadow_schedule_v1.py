#!/usr/bin/env python3
"""Install Kyiv shadow polling as a NAS cron job, without modifying existing Cloudflare jobs.
One live Ubilling request no more often than 120 seconds; no Telegram sends.
"""
import argparse,pathlib,subprocess,shutil,os,json
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE")
SCRIPT=ROOT/"rg_telegram_kyiv_ubilling_live_shadow_v1.py"
CRON_MARK="# RG_TELEGRAM_KYIV_SHADOW_V1"
LINE=f"*/2 * * * * /usr/bin/python3 {SCRIPT} once >> {ROOT}/kyiv_shadow.log 2>&1 {CRON_MARK}"
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","audit","apply"]);args=p.parse_args()
 if args.mode=="selftest":
  assert "*/2 " in LINE and " once " in LINE and CRON_MARK in LINE
  print(json.dumps({"selftest":"PASS","publishing_enabled":False}));return
 if not SCRIPT.is_file():
  raise SystemExit("BLOCKED: Kyiv adapter not installed in permanent NAS state directory")
 current=subprocess.run(["crontab","-l"],text=True,capture_output=True)
 if current.returncode not in (0,1):raise SystemExit("BLOCKED: crontab read failed")
 before=current.stdout
 after="\n".join([x for x in before.splitlines() if CRON_MARK not in x]+[LINE])+"\n"
 if args.mode=="audit":
  print(json.dumps({"status":"READY","already_installed":LINE in before,"cron_entries":len(before.splitlines()),"no_changes":True}));return
 if shutil.which("crontab") is None:raise SystemExit("BLOCKED: crontab binary missing")
 backup=ROOT/"cron_before_kyiv_shadow_v1.txt"
 if not backup.exists():backup.write_text(before,"utf-8")
 done=subprocess.run(["crontab","-"],input=after,text=True,capture_output=True)
 if done.returncode:raise SystemExit("BLOCKED: crontab install failed "+done.stderr[:150])
 print(json.dumps({"status":"SHADOW_CRON_INSTALLED","cadence_minutes":2,"publishing_enabled":False,"preserved_other_entries":True}))
if __name__=="__main__":main()
