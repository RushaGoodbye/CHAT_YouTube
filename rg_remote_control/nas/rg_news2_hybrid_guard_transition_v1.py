#!/usr/bin/env python3
"""Transactional conversion of full Cloudflare pause to hybrid selective freeze.
No Telegram polling/sends, no Cloudflare writes, no NAS gate creation.
"""
import argparse,datetime,importlib.util,json,os,pathlib,subprocess,sys
R=pathlib.Path("/volume1/docker"); S=R/"RG_SECRETS"; T=R/"RG_TELEGRAM_STATE"
PAUSE=S/"rg_cloudflare_migration_pause"; FREEZE=S/"rg_cf_moderation_handoff_freeze"
DEPLOY=R/"RG_NAS_AUTO_DEPLOY.sh"; CF=T/"rg_telegram_cf_selective_moderation_handoff_v1.py"
NEWS=R/"RG_TELEGRAM_NEWS_2"
def emit(status,**kw): print(json.dumps({"status":status,"telegram_sends":0,"telegram_polls":0,"cloudflare_writes":0,"nas_gates_changed":False,**kw},ensure_ascii=False))
def validate():
 if os.geteuid()!=0: raise RuntimeError("SUDO_REQUIRED")
 if not PAUSE.is_file() or PAUSE.is_symlink():raise RuntimeError("PAUSE_FILE_MISSING")
 if not FREEZE.is_file() or FREEZE.is_symlink():raise RuntimeError("SELECTIVE_FREEZE_MISSING")
 if not DEPLOY.is_file() or DEPLOY.is_symlink():raise RuntimeError("DEPLOY_FILE_MISSING")
 content=DEPLOY.read_text("utf8")
 if content.count("# RG_NAS_SELECTIVE_MODERATION_FREEZE_V1")!=1:raise RuntimeError("SELECTIVE_DEPLOY_GUARD_MISSING")
 if content.count("# RG_NAS_CLOUDFLARE_MIGRATION_PAUSE_V1")!=1:raise RuntimeError("FULL_DEPLOY_GUARD_MISSING")
 if 'if [ -f "$ROOT/RG_SECRETS/rg_cf_moderation_handoff_freeze" ]; then' not in content:raise RuntimeError("SELECTIVE_GUARD_NOT_CONDITIONAL")
 if subprocess.run(["/bin/sh","-n",str(DEPLOY)],capture_output=True,timeout=8).returncode:raise RuntimeError("DEPLOY_SYNTAX_INVALID")
 if (S/"rg_nas_telegram_cutover_enabled").exists() or (NEWS/"NAS_EXCLUSIVE_OWNER_VERIFIED").exists() or (NEWS/"MODERATION_DELIVERY_ENABLED").exists():raise RuntimeError("BOT_GATE_ALREADY_OPEN")
 spec=importlib.util.spec_from_file_location("rg_hybrid_cf",str(CF));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 t=m.module().env_token()
 actual={k:m.cron(t,k) for k in (m.WORKER,)+m.OTHER}
 if actual!={"rasha-goodbye-air-alerts":["* * * * *"],"rasha-goodbye-content-hub":["* * * * *"],"rasha-goodbye-video-scanner":[]}:
  raise RuntimeError("HYBRID_SCHEDULE_DRIFT")
 if m.owner(t)!="nas":raise RuntimeError("CLOUDFLARE_MODERATION_NOT_NAS")
 backup=T/"rg_cf_cron_pause_v1/original_schedules.json"
 if not backup.is_file():raise RuntimeError("CRON_ROLLBACK_MISSING")
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
 dest=PAUSE.with_name("rg_cloudflare_migration_pause.hybrid_backup_"+stamp)
 if dest.exists():raise RuntimeError("BACKUP_NAME_CONFLICT")
 return dest
def main():
 ap=argparse.ArgumentParser();ap.add_argument("mode",choices=("check","apply"));args=ap.parse_args()
 dest=validate()
 if args.mode=="check":emit("HYBRID_GUARD_TRANSITION_READY",would_backup_to=dest.name);return
 PAUSE.rename(dest)
 try:
  # Verify selective guard stays effective with the former pause gone.
  if not FREEZE.is_file() or PAUSE.exists() or not DEPLOY.is_file():
   raise RuntimeError("POST_TRANSITION_GUARD_INVALID")
 except Exception:
  dest.rename(PAUSE);raise
 emit("HYBRID_SELECTIVE_GUARD_ACTIVE",full_pause_backup=dest.name,cloudflare_crons_unchanged=True,
   next_step="Reconcile native polling receipt and activate only via verified owner proof")
if __name__=="__main__":
 try:main()
 except Exception as e:
  reason=str(e)
  if not reason.isupper() or len(reason)>90: reason=type(e).__name__
  emit("BLOCKED",reason=reason);sys.exit(1)
