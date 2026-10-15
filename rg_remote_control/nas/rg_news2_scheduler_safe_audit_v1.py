#!/usr/bin/env python3
"""Read-only NAS poller/scheduler inventory; never displays commands, secrets or tokens."""
from __future__ import print_function
import json,os,pathlib,subprocess,datetime,re
BASE=pathlib.Path("/volume1/docker")
TERMS=("getupdates","rg_moderation.py","rg_telegram_nas_native_bot","moderation_tick.sh","telegram_poll","poll-once")
def cmd(a,timeout=12):
 try:
  p=subprocess.run(a,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout)
  return p.stdout if p.returncode==0 else ""
 except Exception:return ""
def scan_text(text):
 hits=[]
 for n,line in enumerate(text.splitlines(),1):
  if any(x in line.lower() for x in TERMS):
   hits.append({"line":n,"mentions":[t for t in TERMS if t in line.lower()]})
 return hits[:30]
def main():
 checks={}
 for label,path in (("nas_scheduler",BASE/"RG_NAS_SCHEDULER_TICK.sh"),("root_cron",pathlib.Path("/etc/crontab"))):
  checks[label]={"exists":path.is_file(),"matches":scan_text(path.read_text("utf-8","replace")) if path.is_file() else []}
 for who in ("root",):
  txt=cmd(["crontab","-l","-u",who])
  checks["cron_"+who]={"available":bool(txt),"matches":scan_text(txt)}
 procs=[]
 for p in pathlib.Path("/proc").iterdir():
  if not p.name.isdigit():continue
  try:
   txt=(p/"cmdline").read_bytes().replace(b"\x00",b" ").decode("utf-8","replace").lower()
   if any(w in txt for w in TERMS) and "rg_news2" not in txt:
    procs.append({"pid":int(p.name),"exe":os.path.basename(os.readlink(str(p/"exe"))),"matches":[t for t in TERMS if t in txt]})
  except Exception:pass
 checks["processes"]=procs[:25]
 docker="/usr/local/bin/docker"
 names=cmd([docker,"ps","--format","{{.Names}}"]).splitlines()
 out=[]
 for name in names:
  if not (name.startswith("rg-") or "telegram" in name):continue
  raw=cmd([docker,"inspect","--format","{{json .Config.Cmd}}",name])
  out.append({"name":name,"matches":[t for t in TERMS if t in raw.lower()]})
 checks["containers"]=out
 checks["owner_gate"]=(BASE/"RG_TELEGRAM_NEWS_2/NAS_EXCLUSIVE_OWNER_VERIFIED").exists()
 checks["delivery_gate"]=(BASE/"RG_TELEGRAM_NEWS_2/MODERATION_DELIVERY_ENABLED").exists()
 checks["legacy_gate"]=(BASE/"RG_SECRETS/rg_nas_telegram_cutover_enabled").exists()
 print(json.dumps({"schema":"RG_NEWS2_SCHEDULER_SAFE_AUDIT_V1","checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"read_only":True,"no_telegram_api":True,"no_secrets_displayed":True,"checks":checks,"sole_getupdates_owner_verified":False},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
