#!/usr/bin/env python3
"""Install the Kyiv shadow poll into existing Synology NAS scheduler tick.
No crontab edits, no external calls, no Telegram sends. Atomic backup+shell syntax validation.
"""
import pathlib,subprocess,shutil,tempfile,os,json,datetime,sys
SCHED=pathlib.Path("/volume1/docker/RG_NAS_SCHEDULER_TICK.sh")
WORKER=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/rg_telegram_kyiv_ubilling_live_shadow_v1.py")
MARK="# RG_KYIV_SHADOW_POLL_BEGIN"
END="# RG_KYIV_SHADOW_POLL_END"
HOOK='''# RG_KYIV_SHADOW_POLL_BEGIN
# Noncritical shadow-only poll; provider requests capped by module cache and 429 cooldown.
if [ -f "/volume1/docker/RG_TELEGRAM_STATE/rg_telegram_kyiv_ubilling_live_shadow_v1.py" ]; then
  /usr/bin/python3 /volume1/docker/RG_TELEGRAM_STATE/rg_telegram_kyiv_ubilling_live_shadow_v1.py once >> /volume1/docker/RG_TELEGRAM_STATE/kyiv_shadow.log 2>&1 || true
fi
# RG_KYIV_SHADOW_POLL_END
'''
ANCHOR='AUTODEPLOY="$ROOT/RG_NAS_AUTO_DEPLOY.sh"'
def main():
 mode=sys.argv[1] if len(sys.argv)>1 else "audit"
 if mode not in ("audit","apply","selftest"):raise SystemExit("mode audit|apply|selftest")
 if mode=="selftest":
  example="#!/bin/sh\n"+ANCHOR+"\n"
  assert (example.replace(ANCHOR,HOOK+"\n"+ANCHOR)).count(MARK)==1
  print(json.dumps({"selftest":"PASS","crontab_required":False}));return
 if not SCHED.is_file() or SCHED.is_symlink() or not WORKER.is_file():
  raise SystemExit("BLOCKED: existing Synology scheduler or live adapter missing")
 before=SCHED.read_text("utf-8")
 if MARK in before:
  print(json.dumps({"status":"ALREADY_INSTALLED","changed":False}));return
 if before.count(ANCHOR)!=1:raise SystemExit("BLOCKED: unexpected scheduler layout")
 after=before.replace(ANCHOR,HOOK+"\n"+ANCHOR)
 check=subprocess.run(["/bin/sh","-n"],input=after,text=True,capture_output=True)
 if check.returncode:raise SystemExit("BLOCKED: shell syntax")
 if mode=="audit":
  print(json.dumps({"status":"PATCH_READY","crontab_required":False,"publishing_enabled":False,"changed":False}));return
 backup=SCHED.with_name(SCHED.name+".backup-kyiv-shadow-"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
 shutil.copy2(SCHED,backup)
 fd,tmp=tempfile.mkstemp(prefix=".rg-sched-",dir=str(SCHED.parent))
 try:
  with os.fdopen(fd,"w") as stream:stream.write(after)
  shutil.copymode(SCHED,tmp)
  os.replace(tmp,SCHED)
 finally:pathlib.Path(tmp).unlink(missing_ok=True)
 print(json.dumps({"status":"SHADOW_HOOK_INSTALLED","backup":str(backup),"crontab_required":False,"publishing_enabled":False,"scheduler_not_executed":True}))
if __name__=="__main__":main()
