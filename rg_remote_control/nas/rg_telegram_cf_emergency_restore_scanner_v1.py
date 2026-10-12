#!/usr/bin/env python3
"""Emergency RESTORE of the old Cloudflare video scanner, not a new migration.

Restores the exact original scanner worker source/config saved BEFORE the NAS
handoff, by building in a TEMPORARY Docker container. The production NAS source
is not mutated during build/deploy. Cloudflare's existing alert and content
Workers remain untouched. Fail closed if any ownership/backup/quota check fails.
No Telegram polling, bot gate changes or message sends in this script.
"""
import argparse,datetime,hashlib,importlib.util,json,os,pathlib,re,shutil,stat,subprocess,sys,tempfile,time

ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SECRETS=ROOT/"RG_SECRETS"
OUT=STATE/"rg_cf_moderation_handoff_v1"
WORKER=ROOT/"RG_DEPLOY/cloudflare-video-moderation"
ENV=ROOT/"RG_DEPLOY/deploy.env"
GATE=SECRETS/"rg_nas_telegram_cutover_enabled"
FREEZE=SECRETS/"rg_cf_moderation_handoff_freeze"
FULLPAUSE=SECRETS/"rg_cloudflare_migration_pause"
VIDEO="rasha-goodbye-video-scanner"
ALERTS="rasha-goodbye-air-alerts"
CONTENT="rasha-goodbye-content-hub"
BACKUPS=(OUT/"quota-entry-v2.js.before",OUT/"wrangler.toml.before")

def emit(status,**fields):
 print(json.dumps({"status":status,"telegram_polls":0,"telegram_sends":0,
  "nas_gate_opened":False,**fields},ensure_ascii=False),flush=True)

def get_module(file,name):
 if file.is_symlink() or not file.is_file():raise RuntimeError(name+"_NOT_INSTALLED")
 spec=importlib.util.spec_from_file_location("rg_recovery_"+name,str(file))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module

def helper():
 return get_module(STATE/"rg_telegram_cf_selective_scanner_stop_v1.py","SCANNER_HELPER")

def cfhelper():
 return get_module(STATE/"rg_telegram_cf_cron_pause_v1.py","CF_NETWORK_HELPER")

def current(token):
 cf=cfhelper()
 return {name:cf.cf_call(token,"GET",name) for name in (VIDEO,ALERTS,CONTENT)}

def owner(token):
 return helper().get_scanner_owner(token)

def backup_sources():
 if OUT.is_symlink() or not OUT.is_dir():raise RuntimeError("BACKUP_DIRECTORY_MISSING")
 for file in BACKUPS:
  if file.is_symlink() or not file.is_file() or file.stat().st_size<100:
   raise RuntimeError("SCANNER_ORIGINAL_BACKUP_MISSING")
 js,toml=(p.read_text("utf-8") for p in BACKUPS)
 if "export class ScannerCoordinator" not in js and "class ScannerCoordinator" not in js:
  raise RuntimeError("SCANNER_ORIGINAL_CODE_INVALID")
 if 'name = "rasha-goodbye-video-scanner"' not in toml or 'main = "src/quota-entry-v2.js"' not in toml:
  raise RuntimeError("SCANNER_ORIGINAL_CONFIG_INVALID")
 if 'crons = ["*/5 * * * *"]' not in toml:
  raise RuntimeError("SCANNER_ORIGINAL_CRON_INVALID")
 if 'RG_MIGRATION_SCANNER_OWNER = "nas"' in toml:
  raise RuntimeError("SCANNER_BACKUP_IS_NAS_OWNER")
 return js,toml

def preflight():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if GATE.exists() or FULLPAUSE.exists():raise RuntimeError("OTHER_CUTOVER_ACTIVE")
 if not FREEZE.is_file() or FREEZE.is_symlink():
  raise RuntimeError("MIGRATION_REDEPLOY_FREEZE_MISSING")
 if not ENV.is_file() or ENV.is_symlink():raise RuntimeError("SCANNER_DEPLOY_ENV_MISSING")
 if WORKER.is_symlink() or not (WORKER/"package.json").is_file():
  raise RuntimeError("SCANNER_DEPLOY_FOLDER_MISSING")
 for path in (WORKER/"src/quota-entry-v2.js",WORKER/"wrangler.toml"):
  if path.is_symlink() or not path.is_file():raise RuntimeError("SCANNER_LIVE_SOURCE_MISSING")
 if (ROOT/"RG_NAS_STATE/deploy.lock").exists():
  raise RuntimeError("ANOTHER_NAS_DEPLOY_ACTIVE")
 js,toml=backup_sources()
 cf=cfhelper();tok=cf.env_token()
 live=current(tok);own=owner(tok)
 if live[ALERTS]!=["* * * * *"] or live[CONTENT]!=["* * * * *"]:
  raise RuntimeError("ALERT_OR_CONTENT_SCHEDULE_CHANGED")
 if live[VIDEO] not in ([],["*/5 * * * *"]):
  raise RuntimeError("SCANNER_SCHEDULE_UNEXPECTED")
 if own not in ("nas","cloudflare","UNDECLARED"):
  raise RuntimeError("SCANNER_REMOTE_OWNER_UNKNOWN")
 if own in ("cloudflare","UNDECLARED") and live[VIDEO]==["*/5 * * * *"]:
  return {"already_restored":True,"remote_owner":own,"crons":live}
 if own!="nas" or live[VIDEO]!=[]:
  raise RuntimeError("UNEXPECTED_PARTIAL_RESTORE")
 # Free-tier Cloudflare deployment quota: refuse rather than disable anything.
 quota=ROOT/"RG_NAS_STATE/cloudflare_quota_resume_epoch"
 if quota.is_file() and not quota.is_symlink():
  try:until=int(quota.read_text("utf-8").strip())
  except (OSError,ValueError):until=0
  if until>int(time.time())+30:raise RuntimeError("CLOUDFLARE_DEPLOY_QUOTA_COOLDOWN")
 support=helper();cli=support.docker_cli();engine=support.docker_daemon(cli)
 return {"already_restored":False,"remote_owner":own,"crons":live,
  "docker":cli,"docker_engine":engine,
  "backup_js_sha16":hashlib.sha256(js.encode()).hexdigest()[:16],
  "backup_cfg_sha16":hashlib.sha256(toml.encode()).hexdigest()[:16]}

def docker_restore(c):
 # Read-only NAS binds and no source changes. Work happens only inside
 # /tmp/rg-scanner-restore in the container; env_file only inside process.
 command="""set -eu
mkdir -p /tmp/rg-scanner-restore
cp -a /source/. /tmp/rg-scanner-restore/
cp /originals/quota-entry-v2.js.before /tmp/rg-scanner-restore/src/quota-entry-v2.js
cp /originals/wrangler.toml.before /tmp/rg-scanner-restore/wrangler.toml
cd /tmp/rg-scanner-restore
npm install --no-audit --no-fund
npm run check
npx --no-install wrangler deploy --config wrangler.toml
"""
 cmd=[c["docker"],"run","--rm","--env-file",str(ENV),
      "-v",str(WORKER)+":/source:ro",
      "-v",str(OUT)+":/originals:ro",
      "-w","/tmp","node:22-bookworm-slim","sh","-lc",command]
 try:p=subprocess.run(cmd,capture_output=True,text=True,timeout=560)
 except (OSError,subprocess.TimeoutExpired):
  emit("CLOUDFLARE_SCANNER_RESTORE_UNCERTAIN",reason="CONTAINER_TIMEOUT_OR_LAUNCH",
   remote_verification_required=True)
  return False
 if p.returncode:
  logs=((p.stdout or "")+"\n"+(p.stderr or "")).lower()
  if any(x in logs for x in ("quota","rate limit","10011")):reason="CLOUDFLARE_DEPLOY_QUOTA"
  elif any(x in logs for x in ("error in wrangler","wrangler","cloudflare")):reason="WRANGLER_OR_REMOTE_DEPLOY"
  elif "npm err" in logs:reason="NPM_BUILD_FAILED"
  else:reason="BUILD_OR_DEPLOY_FAILED"
  emit("CLOUDFLARE_SCANNER_RESTORE_UNCERTAIN",reason=reason,
   exit_code=p.returncode,remote_verification_required=True)
  return False
 return True

def restore():
 c=preflight()
 if c["already_restored"]:
  emit("CLOUDFLARE_SCANNER_ALREADY_RESTORED",remote_owner=c["remote_owner"],
   crons=c["crons"],freeze_retained=True)
  return
 emit("CLOUDFLARE_SCANNER_ROLLBACK_STARTED",
   original_backup_verified=True,alert_and_content_untouched=True,
   local_production_changes=0,original_backup_sha16=c["backup_js_sha16"])
 ok=docker_restore(c)
 if not ok:return
 cf=cfhelper();tok=cf.env_token()
 try:live=current(tok);own=owner(tok)
 except Exception:
  emit("CLOUDFLARE_SCANNER_RESTORE_UNVERIFIED",reason="REMOTE_READBACK_FAILED")
  return
 if live!={VIDEO:["*/5 * * * *"],ALERTS:["* * * * *"],CONTENT:["* * * * *"]}:
  emit("CLOUDFLARE_SCANNER_RESTORE_UNVERIFIED",reason="REMOTE_CRONS_MISMATCH",
   crons=live,remote_owner=own);return
 if own not in ("cloudflare","UNDECLARED"):
  emit("CLOUDFLARE_SCANNER_RESTORE_UNVERIFIED",
   reason="REMOTE_OWNER_STILL_NAS",crons=live,remote_owner=own);return
 # Never touch local production source after restored Worker unless verified.
 # Keep anti-redeploy freeze because the next NAS update would overwrite it.
 OUT.mkdir(exist_ok=True,mode=0o700)
 record=OUT/"scanner_emergency_restore.json"
 if not record.exists():
  fd,tmp=tempfile.mkstemp(prefix=".rg-restored-",dir=str(OUT))
  try:
   with os.fdopen(fd,"w") as file:
    json.dump({"verified_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
      "owner":own,"crons":live,"original_js_sha16":c["backup_js_sha16"],
      "cloudflare_primary":True},file)
   os.chmod(tmp,0o600);os.replace(tmp,record)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 emit("CLOUDFLARE_SCANNER_RESTORED_VERIFIED",owner=own,
  crons=live,cloudflare_alerts_preserved=True,cloudflare_content_preserved=True,
  nas_bot_gate_closed=True,anti_redeploy_freeze_retained=True,
  next_step="verify_fresh_moderation_candidates_and_delivery")

def status():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 tok=cfhelper().env_token()
 emit("CLOUDFLARE_SCANNER_RECOVERY_STATUS",remote_owner=owner(tok),
  crons=current(tok),nas_gate_open=GATE.exists(),
  rollback_receipt=(OUT/"scanner_emergency_restore.json").is_file(),
  originals_present=all(p.is_file() and not p.is_symlink() for p in BACKUPS),
  anti_redeploy_freeze=FREEZE.exists())

def selftest():
 sample='name = "rasha-goodbye-video-scanner"\nmain = "src/quota-entry-v2.js"\ncrons = ["*/5 * * * *"]'
 assert 'name = "rasha-goodbye-video-scanner"' in sample
 assert 'crons = ["*/5 * * * *"]' in sample
 assert any("npx --no-install wrangler deploy --config wrangler.toml" in v
    for v in docker_restore.__code__.co_consts if isinstance(v,str))
 from unittest import mock
 with tempfile.TemporaryDirectory() as td:
  root=pathlib.Path(td)
  first=root/"quota-entry-v2.js.before"
  second=root/"wrangler.toml.before"
  first.write_text("export class ScannerCoordinator { constructor() {} }"+" "*128,encoding="utf-8")
  second.write_text(sample+"\n# preserved original settings"+" "*32+"\n",encoding="utf-8")
  with mock.patch.dict(globals(),{"OUT":root,"BACKUPS":(first,second)}):
   content,config=backup_sources()
   assert "ScannerCoordinator" in content and "*/5" in config
   second.write_text(sample.replace('*/5 * * * *','* * * * *'),encoding="utf-8")
   try:backup_sources()
   except RuntimeError as ex:
    assert str(ex)=="SCANNER_ORIGINAL_CRON_INVALID"
   else:raise AssertionError("bad_original_cron_was_accepted")
 assert GATE!=FREEZE and OUT==STATE/"rg_cf_moderation_handoff_v1"
 emit("CLOUDFLARE_SCANNER_RECOVERY_SELFTEST_PASS",network_calls=0,
  no_source_or_cf_writes=True)
if __name__=="__main__":
 try:
  p=argparse.ArgumentParser()
  p.add_argument("mode",choices=("selftest","preflight","restore","status"))
  mode=p.parse_args().mode
  if mode=="selftest":selftest()
  elif mode=="status":status()
  elif mode=="preflight":
   c=preflight();emit("CLOUDFLARE_SCANNER_ROLLBACK_PREFLIGHT_PASS",
    original_backup_verified=True,**c)
  else:restore()
 except Exception as ex:
  msg=str(ex)
  if not re.fullmatch(r"[A-Z0-9_]{3,110}",msg):msg=type(ex).__name__
  emit("BLOCKED",reason=msg,remote_changes_not_confirmed=True)
  sys.exit(1)
