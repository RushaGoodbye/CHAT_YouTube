#!/usr/bin/env python3
"""Align local alert wrangler cron with already verified live Cloudflare cron.

Safe check/apply, backups mandatory, no Cloudflare writes or Telegram operations.
"""
import argparse,datetime,pathlib,subprocess,sys
P=pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/wrangler.toml")
B=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/rg_cf_moderation_handoff_v1/air_alerts_wrangler.toml.before")
FREEZE=pathlib.Path("/volume1/docker/RG_SECRETS/rg_cf_moderation_handoff_freeze")
OLD='crons = []'
NEW='crons = ["* * * * *"]'
def verify():
 if not FREEZE.is_file() or FREEZE.is_symlink():raise RuntimeError("FREEZE_NOT_PRESENT")
 if P.is_symlink() or not P.is_file() or B.is_symlink() or not B.is_file():raise RuntimeError("SOURCE_OR_BACKUP_MISSING")
 old=P.read_text("utf-8");backup=B.read_text("utf-8")
 if old.count(OLD)!=1 or old.count('RG_MODERATION_RUNTIME_OWNER = "nas"')!=1:raise RuntimeError("SOURCE_NOT_EXPECTED")
 expected=old.replace(OLD,NEW,1)
 bnorm=backup.replace('crons = ["* * * * *"]','crons = ["* * * * *"]')
 if bnorm.count(NEW)!=1:raise RuntimeError("ORIGINAL_CRON_UNKNOWN")
 if expected!=backup.replace('TELEGRAM_CHAT_ID = "@RussiaGoodbyeUA"','TELEGRAM_CHAT_ID = "@RussiaGoodbyeUA"\nRG_MODERATION_RUNTIME_OWNER = "nas"',1):
  raise RuntimeError("UNRELATED_CONFIG_CHANGES")
 return old,expected
def main():
 ap=argparse.ArgumentParser();ap.add_argument("mode",choices=("check","apply"));mode=ap.parse_args().mode
 old,new=verify()
 if mode=="check":
  print("LOCAL_WRANGLER_ALIGNMENT_READY: only cron mismatch; no writes")
  return
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
 backup=P.with_name("wrangler.toml.pre_hybrid_align_"+stamp+".bak")
 if backup.exists():raise RuntimeError("BACKUP_COLLISION")
 import shutil
 shutil.copy2(P,backup)
 # preserve owner, permissions, use atomic replacement
 import tempfile,os,stat
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=P.parent,prefix=".rg_hybrid_",delete=False) as f:
  tmp=pathlib.Path(f.name);f.write(new)
 shutil.copystat(P,tmp)
 os.replace(tmp,P)
 print("LOCAL_WRANGLER_ALIGNED; backup="+str(backup)+"; cloudflare_writes=0; telegram_sends=0")
if __name__=="__main__":
 try:main()
 except Exception as e:print("BLOCKED: "+str(e));sys.exit(1)
