#!/usr/bin/env python3
"""READ-ONLY Cloudflare->NAS pause diagnosis.
No workers modified; no migration marker created; no Telegram API calls.
Works on Synology Python 3.8. Does not print secrets, tokens or environment.
"""
import datetime,importlib.util,json,os,pathlib,re,sys
ROOT=pathlib.Path("/volume1/docker")
MODULE=ROOT/"RG_TELEGRAM_STATE/rg_telegram_cf_cron_pause_v1.py"
ROOT_STATE=ROOT/"RG_TELEGRAM_STATE"
def reason(err):
 msg=str(err)
 if isinstance(err,RuntimeError) and re.fullmatch(r"[A-Za-z0-9_-]{3,140}",msg):
  return msg
 return type(err).__name__
def main():
 report={"status":"CF_PAUSE_READ_ONLY_DIAGNOSIS",
  "telegram_sends":0,"telegram_polls":0,"cloudflare_writes":0,
  "nas_files_changed":False,"checks":{}}
 checks=report["checks"]
 if MODULE.is_symlink() or not MODULE.is_file():
  checks["pause_module"]="MISSING_OR_SYMLINK"
  print(json.dumps(report,ensure_ascii=False));return
 spec=importlib.util.spec_from_file_location("rg_cf_migration_pause_module",str(MODULE))
 m=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(m)
 checks["pause_module"]="PRESENT"
 checks["native_bot_installed"]=(ROOT_STATE/"rg_telegram_nas_native_bot_v01.py").is_file()
 checks["minute_silence_installed"]=(ROOT_STATE/"rg_telegram_nas_minute_silence_v1.py").is_file()
 checks["nas_gate_present"]=(ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled").exists()
 checks["migration_pause_marker_present"]=m.MARKER.exists()
 checks["cron_pause_file_present"]=(m.SESSION/"paused.json").is_file()
 checks["original_schedules_backup_present"]=m.snapshot_path().is_file()
 checks["autodeploy_path"]=str(m.DEPLOY)
 checks["autodeploy_exists"]=m.DEPLOY.is_file() and not m.DEPLOY.is_symlink()
 if checks["autodeploy_exists"]:
  try:
   source=m.DEPLOY.read_text("utf-8")
   changed,patch_status=m.patch(source)
   m.shell_ok(changed)
   checks["autodeploy_guard"]=patch_status
   checks["autodeploy_syntax"]="PASS"
  except Exception as e:checks["autodeploy_guard_error"]=reason(e)
 try:
  m.check_deploy_idle()
  checks["deploy_lock"]="IDLE"
 except Exception as e:
  checks["deploy_lock"]=reason(e)
  lock=m.LOCK
  if lock.is_dir():
   try:
    started=int((lock/"started_at").read_text("utf-8").strip())
    checks["deploy_lock_age_seconds"]=max(0,int(datetime.datetime.now(datetime.timezone.utc).timestamp())-started)
   except Exception:pass
 if checks["original_schedules_backup_present"]:
  try:
   backup=m.state_from_disk()
   checks["backed_up_schedules"]=backup["schedules"]
  except Exception as e:checks["backup_validation_error"]=reason(e)
 try:
  token=m.env_token()
  checks["cloudflare_api_auth"]="TOKEN_READ"
  current=m.report_live(token)
  checks["live_cloudflare_schedules"]=current
  checks["all_three_active"]=all(bool(v) for v in current.values())
  checks["all_three_empty"]=all(not v for v in current.values())
  if "backed_up_schedules" in checks:
   checks["live_equals_backup"]=current==checks["backed_up_schedules"]
 except Exception as e:checks["cloudflare_read_error"]=reason(e)
 ready=(
  checks.get("autodeploy_syntax")=="PASS" and
  checks.get("deploy_lock")=="IDLE" and
  checks.get("all_three_active") is True and
  checks.get("native_bot_installed") is True and
  checks.get("minute_silence_installed") is True and
  checks.get("nas_gate_present") is False and
  checks.get("migration_pause_marker_present") is False and
  "backup_validation_error" not in checks and
  checks.get("live_equals_backup") is not False
 )
 report["pause_preflight_ready"]=ready
 report["recommended_next_step"]="PAUSE_ALLOWED_AFTER_REVIEW" if ready else "DO_NOT_REPEAT_PAUSE_CHECK_BLOCKER"
 print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"CF_PAUSE_DIAGNOSIS_BLOCKED",
   "reason":reason(e),"telegram_sends":0,"telegram_polls":0,
   "cloudflare_writes":0,"nas_files_changed":False}))
  sys.exit(1)
