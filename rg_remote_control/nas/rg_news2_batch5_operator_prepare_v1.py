#!/usr/bin/env python3
"""RG News2 batch 5 — atomic NAS operator prepare, status, rollback.

Prepare installs an inert, gated single-owner moderation service launcher.
This script never creates ownership receipts, never sends to Telegram,
never enables publication, and never changes NAS scheduler/Cloudflare.

The launcher refuses to run without both gates and refuses if legacy NAS
cutover gate is present; runtime flock excludes overlapping runs.
"""
from __future__ import print_function
import datetime,json,os,pathlib,shutil,subprocess,sys,tempfile
N=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
O=N/"operator"
RUN=O/"moderation_service.sh"
LEG=pathlib.Path("/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled")
CONTENT="""#!/bin/sh
set -eu
BASE=/volume1/docker/RG_TELEGRAM_NEWS_2
test -f "$BASE/NAS_EXCLUSIVE_OWNER_VERIFIED" || { echo BLOCKED_OWNER_GATE; exit 20; }
test -f "$BASE/MODERATION_DELIVERY_ENABLED" || { echo BLOCKED_DELIVERY_GATE; exit 21; }
test ! -e /volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled || { echo BLOCKED_LEGACY_GATE; exit 22; }
test ! -e "$BASE/PUBLISH_ENABLED" || { echo BLOCKED_PUBLISH_GATE; exit 24; }
command -v flock >/dev/null 2>&1 || { echo BLOCKED_FLOCK_UNAVAILABLE; exit 25; }
exec 9>"$BASE/operator/moderation_service.lock"
flock -n 9 || { echo BLOCKED_ALREADY_RUNNING; exit 23; }
python3 "$BASE/rg_moderation.py" poll-once
python3 "$BASE/rg_moderation.py" send-one
"""
def state():
 return {"schema":"RG_NEWS2_BATCH5_OPERATOR_PREP_V1","runner_installed":RUN.is_file() and not RUN.is_symlink(),
  "owner_gate":(N/"NAS_EXCLUSIVE_OWNER_VERIFIED").is_file(),
  "delivery_gate":(N/"MODERATION_DELIVERY_ENABLED").is_file(),
  "publish_gate":(N/"PUBLISH_ENABLED").exists(),
  "legacy_gate":LEG.exists(),
  "exclusive_poll_owner_proven_by_this_package":False,
  "telegram_calls":0,"news_db_writes":0,"cron_changed":False}
def emit(x):print(json.dumps(x,ensure_ascii=False,indent=2))
def main():
 mode=sys.argv[1] if len(sys.argv)==2 else ""
 if mode not in ("status","prepare","rollback"):
  print("usage: batch5.py status|prepare|rollback");return 2
 if mode=="status":
  emit(state());return 0
 if os.geteuid()!=0:
  emit({"result":"BLOCKED_SUDO_REQUIRED"});return 1
 if O.is_symlink() or RUN.is_symlink():
  emit({"result":"BLOCKED_SYMLINK"});return 1
 if mode=="rollback":
  if RUN.is_file():
   stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
   dest=O/("moderation_service.disabled_"+stamp)
   if dest.exists():emit({"result":"BACKUP_COLLISION"});return 1
   os.rename(str(RUN),str(dest))
   emit({"result":"SERVICE_LAUNCHER_DISABLED","retained_backup":str(dest),"telegram_calls":0,"cron_changed":False})
  else:emit({"result":"ALREADY_DISABLED"})
  return 0
 if not (N/"rg_moderation.py").is_file() or not (N/"news.sqlite3").is_file():
  emit({"result":"BLOCKED_NEWS2_MISSING"});return 1
 if (N/"PUBLISH_ENABLED").exists() or LEG.exists():
  emit({"result":"BLOCKED_PREEXISTING_GATE"});return 1
 check=subprocess.run(["/bin/sh","-n"],input=CONTENT,universal_newlines=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if check.returncode:emit({"result":"BLOCKED_SYNTAX"});return 1
 O.mkdir(mode=0o700,exist_ok=True)
 os.chmod(str(O),0o700)
 if RUN.is_file() and RUN.read_text(encoding="utf-8")==CONTENT:
  emit(dict(state(),result="ALREADY_PREPARED_NOT_ACTIVE"));return 0
 if RUN.is_file():
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  backup=O/("moderation_service.backup_"+stamp)
  if backup.exists():emit({"result":"BACKUP_COLLISION"});return 1
  shutil.copy2(str(RUN),str(backup));os.chmod(str(backup),0o600)
 fd,tmp=tempfile.mkstemp(prefix=".news2_launcher_",dir=str(O))
 try:
  with os.fdopen(fd,"w") as fp:fp.write(CONTENT)
  os.chmod(tmp,0o700)
  os.rename(tmp,str(RUN))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 emit(dict(state(),result="PREPARED_NOT_ACTIVE",next="Independent Telegram polling ownership proof required before enabling gates and scheduler"))
 return 0
if __name__=="__main__":
 try:sys.exit(main())
 except Exception as e:
  emit({"result":"BLOCKED","error_type":type(e).__name__});sys.exit(1)
