#!/usr/bin/env python3
"""Hybrid recovery, stage 1: Cloudflare alerts/content only; scanner remains disabled.

Default 'check' is read-only. 'apply' writes exactly two Cron schedules after
strict readback, preserves full-pause marker and leaves all NAS/Telegram gates off.
"""
import argparse,datetime,importlib.util,json,os,pathlib,sys
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SECRETS=ROOT/"RG_SECRETS"
PAUSE=SECRETS/"rg_cloudflare_migration_pause"
FREEZE=SECRETS/"rg_cf_moderation_handoff_freeze"
RECEIPT=STATE/"rg_cf_moderation_handoff_v1/scanner_guard_deployed.json"
SCANNER_MODULE=STATE/"rg_telegram_cf_selective_scanner_stop_v1.py"
PAUSE_MODULE=STATE/"rg_telegram_cf_cron_pause_v1.py"
NAMES=("rasha-goodbye-air-alerts","rasha-goodbye-content-hub")
SCANNER="rasha-goodbye-video-scanner"
def emit(status,**kwargs):
 print(json.dumps({"status":status,"telegram_polls":0,"telegram_sends":0,"nas_gates_unchanged":True,**kwargs},ensure_ascii=False))
def load(path,label):
 if not path.is_file() or path.is_symlink():raise RuntimeError(label+"_MISSING")
 spec=importlib.util.spec_from_file_location(label,str(path))
 obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
 return obj
def check():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if not PAUSE.is_file() or PAUSE.is_symlink():raise RuntimeError("FULL_PAUSE_MARKER_UNEXPECTED")
 if not FREEZE.is_file() or FREEZE.is_symlink():raise RuntimeError("SELECTIVE_FREEZE_MISSING")
 if not RECEIPT.is_file() or RECEIPT.is_symlink():raise RuntimeError("SCANNER_GUARD_RECEIPT_MISSING")
 if (SECRETS/"rg_nas_telegram_cutover_enabled").exists():raise RuntimeError("NAS_CUTOVER_ALREADY_ACTIVE")
 m=load(PAUSE_MODULE,"rg_hybrid_pause")
 snapshot=m.state_from_disk()["schedules"]
 if snapshot.get(SCANNER)!=["*/5 * * * *"] or any(snapshot.get(k)!=["* * * * *"] for k in NAMES):
  raise RuntimeError("BACKUP_SCHEDULE_DRIFT")
 token=m.env_token()
 actual={name:m.cf_call(token,"GET",name) for name in (SCANNER,)+NAMES}
 if actual[SCANNER]!=[]:raise RuntimeError("SCANNER_CRON_ACTIVE")
 if any(actual[k] not in ([],snapshot[k]) for k in NAMES):raise RuntimeError("UNKNOWN_EXISTING_CRON")
 c=load(SCANNER_MODULE,"rg_hybrid_scanner")
 if c.get_scanner_owner(token)!="nas":raise RuntimeError("SCANNER_DO_OWNER_UNVERIFIED")
 return m,token,snapshot,actual
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=("check","apply"))
 mode=p.parse_args().mode
 m,token,backup,current=check()
 if mode=="check":
  emit("HYBRID_STAGE1_PREFLIGHT_PASS",current=current,desired={k:backup[k] for k in NAMES},
       scanner_preserved_disabled=True,full_pause_marker_kept=True,no_remote_writes=True)
  return
 modified=[]
 try:
  for name in NAMES:
   if current[name]==backup[name]:continue
   result=m.cf_call(token,"PUT",name,[{"cron":v} for v in backup[name]])
   if result!=backup[name]:raise RuntimeError("CF_WRITE_READBACK_MISMATCH")
   modified.append(name)
  live={name:m.cf_call(token,"GET",name) for name in (SCANNER,)+NAMES}
  if live[SCANNER]!=[] or any(live[k]!=backup[k] for k in NAMES):
   raise RuntimeError("POST_DEPLOY_SCHEDULE_MISMATCH")
 except Exception:
  # Never retry a possibly successful PUT; operator must reconcile using 'check'.
  emit("HYBRID_STAGE1_RECONCILIATION_REQUIRED",modified_confirmed=modified,
       uncertain_remote_state=True,full_pause_marker_kept=True)
  raise
 emit("HYBRID_STAGE1_RESTORED",live=live,full_pause_marker_kept=True,
      scanner_cron_disabled=True,nas_cutover_not_enabled=True,
      next_step="Verify live alerts/content and Cloudflare polling handoff before removing the pause marker")
if __name__=="__main__":
 try:main()
 except Exception as e:
  msg=str(e)
  if not msg.isupper() or len(msg)>90:msg=type(e).__name__
  emit("BLOCKED",reason=msg);sys.exit(1)
