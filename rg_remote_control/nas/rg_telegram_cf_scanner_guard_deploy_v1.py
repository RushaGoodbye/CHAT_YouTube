#!/usr/bin/env python3
"""Deploy only guarded CF video scanner to stop its independent DO alarm.
No Telegram polling, no channel sends, does not touch alert/content Workers.
Requires prior user-authorized pause of ALL THREE Cloudflare Cron schedules.
"""
import argparse,datetime,json,os,pathlib,re,shutil,subprocess,sys,tempfile,urllib.error,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
STAGED=STATE/"cf_moderation_handoff_stage_v1"
SESSION=STATE/"rg_cf_cron_pause_v1"
SECRETS=ROOT/"RG_SECRETS"
MARKER=SECRETS/"rg_cloudflare_migration_pause"
WORKER=ROOT/"RG_DEPLOY/cloudflare-video-moderation"
ENV=ROOT/"RG_DEPLOY/deploy.env"
ACCOUNT="be73f73dbe2a5471c62384dc673c91e6"
NAMES=("rasha-goodbye-video-scanner","rasha-goodbye-air-alerts","rasha-goodbye-content-hub")
PREFIX="RG_MIGRATION_SCANNER_OWNER = "
def emit(status,**kw):
 print(json.dumps({"status":status,"telegram_polls":0,"telegram_sends":0,
 "nas_gate_opened":False,**kw},ensure_ascii=False),flush=True)
def token():
 for file in (ROOT/"RG_ALERTS_DEPLOY/deploy.env",ENV):
  if not file.is_file() or file.is_symlink():continue
  s=file.read_text("utf-8")
  m=re.search(r"^\s*(?:export\s+)?(?:CLOUDFLARE_API_TOKEN|CF_API_TOKEN|CLOUDFLARE_TOKEN)\s*=\s*(.+?)\s*$",s,re.M)
  if m:
   v=m.group(1).strip("'\" ")
   if len(v)>=25 and "$" not in v:return v
 raise RuntimeError("CF_API_TOKEN_UNAVAILABLE")
def get_json(url,auth):
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+auth,"User-Agent":"RG-NAS-DO-Guard/1"})
 try:
  with urllib.request.urlopen(req,timeout=14) as r:j=json.loads(r.read(131072))
 except urllib.error.HTTPError as e:raise RuntimeError(f"CF_READ_HTTP_{e.code}") from None
 except (urllib.error.URLError,ValueError,OSError):raise RuntimeError("CF_READ_FAILED") from None
 if not isinstance(j,dict) or j.get("success") is not True:raise RuntimeError("CF_READ_REJECTED")
 return j.get("result")
def cf_verified(auth):
 schedules={}
 for name in NAMES:
  result=get_json(f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts/{name}/schedules",auth)
  rows=result.get("schedules") if isinstance(result,dict) else None
  if not isinstance(rows,list):raise RuntimeError("CF_BAD_SCHEDULES")
  schedules[name]=[x.get("cron") for x in rows if isinstance(x,dict)]
 if any(schedules.values()):raise RuntimeError("CF_CRON_PAUSE_INCOMPLETE")
 return schedules
def published_guard(auth):
 result=get_json(f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts/{NAMES[0]}/settings",auth)
 bindings=result.get("bindings") if isinstance(result,dict) else None
 if not isinstance(bindings,list):return False
 return any(x.get("name")=="RG_MIGRATION_SCANNER_OWNER" and x.get("type")=="plain_text" and x.get("text")=="nas" for x in bindings if isinstance(x,dict))
def check_source():
 if not STAGED.is_dir() or STAGED.is_symlink():raise RuntimeError("MIGRATION_STAGE_ABSENT")
 p=STAGED/"scanner_worker.js"
 t=STAGED/"scanner_worker.toml"
 if not p.is_file() or not t.is_file():raise RuntimeError("SCANNER_STAGE_ABSENT")
 code=p.read_text("utf-8");config=t.read_text("utf-8")
 checks={"owner_conditional":'RG_MIGRATION_SCANNER_OWNER || "cloudflare"' in code,
 "delete_alarm":code.count("deleteAlarm()")>=3,
 "do_stop_log":"DO_ALARM_STOPPED_NAS_OWNER" in code,
 "default_cf":'RG_MIGRATION_SCANNER_OWNER = "cloudflare"' in config,
 "cron":'crons = ["*/5 * * * *"]' in config,
 "worker_name":'name = "rasha-goodbye-video-scanner"' in config}
 if not all(checks.values()):raise RuntimeError("SCANNER_GUARD_STAGE_INVALID")
 nextconf=config.replace('RG_MIGRATION_SCANNER_OWNER = "cloudflare"',
                         'RG_MIGRATION_SCANNER_OWNER = "nas"')
 if nextconf==config or nextconf.count('RG_MIGRATION_SCANNER_OWNER = "nas"')!=1:
  raise RuntimeError("SCANNER_CONFIG_PATCH_INVALID")
 return code,nextconf,checks
def shell_test():
 sample='RG_MIGRATION_SCANNER_OWNER = "cloudflare"'
 assert sample.replace('"cloudflare"','"nas"')=='RG_MIGRATION_SCANNER_OWNER = "nas"'
 assert "deleteAlarm()" in "await state.storage.deleteAlarm()"
 emit("CF_SCANNER_GUARD_SELFTEST_PASS",dry_run=True,no_telegram_calls=True)
def readiness():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if not MARKER.is_file() or MARKER.is_symlink():raise RuntimeError("PAUSE_MARKER_MISSING")
 if not (SESSION/"original_schedules.json").is_file():raise RuntimeError("CRON_BACKUP_MISSING")
 if not (SESSION/"paused.json").is_file():raise RuntimeError("CF_CRON_PAUSE_NOT_CONFIRMED")
 cf_verified(token())
 code,newconfig,checks=check_source()
 if not WORKER.is_dir() or WORKER.is_symlink() or not ENV.is_file():raise RuntimeError("SCANNER_TARGET_UNAVAILABLE")
 for p in (WORKER/"src/quota-entry-v2.js",WORKER/"wrangler.toml"):
  if p.is_symlink() or not p.is_file():raise RuntimeError("SCANNER_PRODUCTION_FILE_MISSING")
 if (ROOT/"RG_NAS_STATE/deploy.lock").exists():raise RuntimeError("OTHER_DEPLOY_IN_PROGRESS")
 report={"checks":checks,"guard_mode":"nas","cron_all_paused":True}
 return code,newconfig,report
def deploy():
 code,config,report=readiness()
 if published_guard(token()):
  emit("CF_SCANNER_GUARD_ALREADY_DEPLOYED",**report,cloudflare_live_owner="nas")
  return
 outdir=SESSION/"scanner_guard_backup"
 if outdir.is_symlink():raise RuntimeError("BACKUP_SYMLINK")
 outdir.mkdir(exist_ok=True,parents=True,mode=0o700)
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
 targets={"quota-entry-v2.js":WORKER/"src/quota-entry-v2.js","wrangler.toml":WORKER/"wrangler.toml"}
 for name,file in targets.items():shutil.copy2(file,outdir/(name+"."+stamp+".bak"))
 replacements={"quota-entry-v2.js":code,"wrangler.toml":config}
 for name,file in targets.items():
  fd,tmp=tempfile.mkstemp(dir=str(file.parent),prefix=".rg-do-guard-")
  try:
   with os.fdopen(fd,"w",encoding="utf-8") as fh:fh.write(replacements[name])
   shutil.copymode(file,tmp);os.replace(tmp,file)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 cmd=["docker","run","--rm","--env-file",str(ENV),"-v",str(WORKER)+":/app",
      "-w","/app","node:22-bookworm-slim","sh","-lc",
      "npm install --no-audit --no-fund && npx wrangler deploy --config wrangler.toml"]
 emit("CF_SCANNER_GUARD_DEPLOY_START",**report,cloudflare_writes_started=True,
      source_backup_saved=True,alerts_worker_untouched=True,content_worker_untouched=True)
 try:
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=450)
 except (subprocess.TimeoutExpired,OSError):
  emit("CF_SCANNER_GUARD_DEPLOY_UNCERTAIN",reason="DEPLOY_TIMEOUT_OR_RUNTIME",
       verification_required=True,live_nas_gate_closed=True)
  return
 if p.returncode!=0:
  # Do NOT assume an exit code tells whether a remote worker was updated.
  message=(p.stdout or "")+"\n"+(p.stderr or "")
  cl="cloudflare_quota_or_rate_limit" if any(x in message.lower() for x in ("quota","rate limit","error 10011")) else "wrangler_deploy_failed"
  emit("CF_SCANNER_GUARD_DEPLOY_UNCERTAIN",reason=cl,exit_code=p.returncode,
       verification_required=True,live_nas_gate_closed=True)
  return
 if not published_guard(token()):
  emit("CF_SCANNER_GUARD_DEPLOY_UNVERIFIED",reason="owner_binding_missing",
       live_nas_gate_closed=True)
  return
 emit("CF_SCANNER_GUARD_DEPLOYED",owner="nas",do_alarm_next_wake_should_delete=True,
      requires_alarm_confirmation=True,live_nas_gate_closed=True)
def status():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 auth=token()
 schedules=cf_verified(auth)
 emit("CF_SCANNER_GUARD_REMOTE_STATUS",cloudflare_schedules=schedules,
   worker_owner_binding="nas" if published_guard(auth) else "NOT_NAS",
   independent_do_alarm_deleted_confirmed=False,required_next="wait_and_verify_scanner_alarm")
if __name__=="__main__":
 try:
  p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","readiness","deploy","status"))
  a=p.parse_args()
  if a.mode=="selftest":shell_test()
  elif a.mode=="readiness":
   _,_,checks=readiness();emit("CF_SCANNER_GUARD_READY",**checks)
  elif a.mode=="deploy":deploy()
  else:status()
 except Exception as e:
  reason=str(e)
  if not re.fullmatch(r"[A-Z0-9_]{3,80}",reason):reason=type(e).__name__
  emit("BLOCKED",reason=reason,live_nas_gate_closed=True)
  sys.exit(1)
