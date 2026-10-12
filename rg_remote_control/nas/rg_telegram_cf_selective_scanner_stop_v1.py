#!/usr/bin/env python3
"""Stop ONLY legacy Cloudflare video scanner (Cron + Durable Object alarm)
as the first phase of a selective Telegram moderation handoff.
Keep rasha-goodbye-air-alerts and rasha-goodbye-content-hub Cron active.
Does not change Telegram bot polling or the NAS publication gate.
"""
import argparse,datetime,importlib.util,json,os,pathlib,re,shutil,subprocess,sys,tempfile
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE";SECRETS=ROOT/"RG_SECRETS"
OUT=STATE/"rg_cf_moderation_handoff_v1"
STAGED=STATE/"cf_moderation_handoff_stage_v1"
WORKER=ROOT/"RG_DEPLOY/cloudflare-video-moderation"
ENV=ROOT/"RG_DEPLOY/deploy.env"
DEPLOYER=ROOT/"RG_NAS_AUTO_DEPLOY.sh"
FREEZE=SECRETS/"rg_cf_moderation_handoff_freeze"
FULLPAUSE=SECRETS/"rg_cloudflare_migration_pause"
GATE=SECRETS/"rg_nas_telegram_cutover_enabled"
VIDEO="rasha-goodbye-video-scanner";ALERTS="rasha-goodbye-air-alerts";CONTENT="rasha-goodbye-content-hub"
MARK="# RG_NAS_SELECTIVE_MODERATION_FREEZE_V1"
ANCHOR="acquire_deploy_lock\nnote_owner_state RUNNING"
GUARD='''# RG_NAS_SELECTIVE_MODERATION_FREEZE_V1
if [ -f "$ROOT/RG_SECRETS/rg_cf_moderation_handoff_freeze" ]; then
  note_owner_state PAUSED_SELECTIVE_MODERATION_HANDOFF
  printf '%s\n' "RG_NAS_CF_AUTO_DEPLOY_FROZEN_FOR_MODERATION"
  exit 0
fi

'''
def emit(status,**x):
 print(json.dumps({"status":status,"telegram_sends":0,"telegram_polls":0,
   "nas_gate_opened":False,**x},ensure_ascii=False),flush=True)
def mod():
 p=STATE/"rg_telegram_cf_cron_pause_v1.py"
 if p.is_symlink() or not p.is_file():raise RuntimeError("CF_NETWORK_HELPER_MISSING")
 spec=importlib.util.spec_from_file_location("rg_selective_scanner_cf_helper",str(p))
 obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
 return obj
def sel():
 p=STATE/"rg_telegram_cf_selective_moderation_handoff_v1.py"
 if p.is_symlink() or not p.is_file():raise RuntimeError("SELECTIVE_CUTOVER_MODULE_MISSING")
 spec=importlib.util.spec_from_file_location("rg_selective_scanner_handoff_helper",str(p))
 obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
 return obj
def snapshot(token):
 s=sel()
 return {x:s.cron(token,x) for x in (VIDEO,ALERTS,CONTENT)}
def allowed():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if GATE.exists() or FULLPAUSE.exists():raise RuntimeError("OTHER_CUTOVER_ALREADY_ACTIVE")
 if not (STAGED/"scanner_worker.js").is_file() or not (STAGED/"scanner_worker.toml").is_file():
  raise RuntimeError("PINNED_SCANNER_SOURCE_MISSING")
 if not ENV.is_file() or ENV.is_symlink():raise RuntimeError("SCANNER_DEPLOY_ENV_MISSING")
 if not WORKER.is_dir():raise RuntimeError("SCANNER_SOURCE_MISSING")
 if (ROOT/"RG_NAS_STATE/deploy.lock").exists():raise RuntimeError("AUTO_DEPLOY_IN_PROGRESS")
 # Do not pause the legacy scanner if Cloudflare's deployment quota is in
 # cooldown: its independent DO alarm cannot be disabled without redeploying.
 quota=ROOT/"RG_NAS_STATE/cloudflare_quota_resume_epoch"
 if quota.is_file() and not quota.is_symlink():
  import time
  try:next_allowed=int(quota.read_text("utf-8").strip())
  except (OSError,ValueError):next_allowed=0
  if next_allowed>int(time.time())+30:
   raise RuntimeError("CLOUDFLARE_DEPLOY_QUOTA_COOLDOWN")
 if not DEPLOYER.is_file() or DEPLOYER.is_symlink():raise RuntimeError("AUTODEPLOY_SOURCE_MISSING")
def guard_source():
 source=(STAGED/"scanner_worker.js").read_text("utf-8")
 config=(STAGED/"scanner_worker.toml").read_text("utf-8")
 if ("RG_MIGRATION_SCANNER_OWNER" not in source or
     source.count("deleteAlarm()")<3 or "DO_ALARM_STOPPED_NAS_OWNER" not in source):
  raise RuntimeError("SCANNER_DO_ALARM_GUARD_MISSING")
 if 'RG_MIGRATION_SCANNER_OWNER = "cloudflare"' not in config:raise RuntimeError("SCANNER_DEFAULT_OWNER_MISSING")
 if 'crons = ["*/5 * * * *"]' not in config:raise RuntimeError("SCANNER_CRON_ANCHOR_MISSING")
 cfg=config.replace('RG_MIGRATION_SCANNER_OWNER = "cloudflare"','RG_MIGRATION_SCANNER_OWNER = "nas"')
 cfg=cfg.replace('crons = ["*/5 * * * *"]','crons = []')
 return source,cfg
def preflight():
 allowed();guard_source()
 t=mod().env_token()
 live=snapshot(t)
 if live!={VIDEO:["*/5 * * * *"],ALERTS:["* * * * *"],CONTENT:["* * * * *"]}:
  raise RuntimeError("CLOUDFLARE_BASELINE_SCHEDULE_CHANGED")
 if sel().owner(t) not in ("cloudflare","UNDECLARED"):
  raise RuntimeError("ALERT_OWNER_NOT_CLOUDFLARE")
 return live
def save(p,data):
 if p.is_symlink():raise RuntimeError("SYMLINK_REFUSED")
 fd,t=tempfile.mkstemp(prefix=".rg-scanner-",dir=str(p.parent))
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(data)
  os.chmod(t,0o600);os.replace(t,p)
 finally:
  if os.path.exists(t):os.unlink(t)
def prefreeze():
 # Establish anti-redeployment guard before any Cloudflare schedule writes.
 if FREEZE.exists():return
 dep=DEPLOYER.read_text("utf-8")
 if MARK in dep:
  patched=dep
 else:
  if dep.count(ANCHOR)!=1:raise RuntimeError("AUTODEPLOY_ANCHOR_MISSING")
  patched=dep.replace(ANCHOR,GUARD+ANCHOR,1)
 check=subprocess.run(["/bin/sh","-n"],input=patched,text=True,capture_output=True,timeout=6)
 if check.returncode:raise RuntimeError("AUTODEPLOY_PATCH_SYNTAX_INVALID")
 OUT.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(OUT,0o700)
 if not (OUT/"RG_NAS_AUTO_DEPLOY.sh.before").exists():
  save(OUT/"RG_NAS_AUTO_DEPLOY.sh.before",dep)
 if dep!=patched:
  import stat
  mode=stat.S_IMODE(DEPLOYER.stat().st_mode)
  save(DEPLOYER,patched);os.chmod(DEPLOYER,mode)
 save(FREEZE,json.dumps({"purpose":"stop_legacy_scanner_and_handoff_to_nas",
   "created_at":datetime.datetime.now(datetime.timezone.utc).isoformat()})+"\n")
def stop_scanner():
 live=preflight()
 prefreeze()
 t=mod().env_token()
 # Durable backup is written before sending the first change to Cloudflare.
 save(OUT/"scanner_original_cron.json",json.dumps(live,ensure_ascii=False)+"\n")
 try:
  mod().cf_call(t,"PUT",VIDEO,[])
 except Exception:
  # Reconcile uncertain one-shot write by reading back, not repeating it.
  observed=snapshot(t)
  if observed[VIDEO]!=[]:
   raise RuntimeError("SCANNER_CRON_STOP_NOT_CONFIRMED") from None
 observed=snapshot(t)
 if observed[VIDEO]!=[] or observed[ALERTS]!=live[ALERTS] or observed[CONTENT]!=live[CONTENT]:
  raise RuntimeError("SCANNER_CRON_STOP_READBACK_FAILED")
 save(OUT/"scanner_cron_paused.json",json.dumps({"at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
   "crons":observed})+"\n")
 emit("CF_LEGACY_SCANNER_CRON_PAUSED",video_cron=[],alerts_cron=observed[ALERTS],
   content_hub_cron=observed[CONTENT],independent_do_alarm="REQUIRES_GUARD_DEPLOY",
   live_mod_bot_still_cloudflare=True)
def resume_scanner_cron():
 """Emergency rollback only if the old Cloudflare scanner is still its owner."""
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if GATE.exists() or FULLPAUSE.exists():raise RuntimeError("OTHER_CUTOVER_ALREADY_ACTIVE")
 t=mod().env_token()
 current=snapshot(t)
 if current[ALERTS]!=["* * * * *"] or current[CONTENT]!=["* * * * *"]:
  raise RuntimeError("ALERT_OR_CONTENT_CRON_NOT_ORIGINAL")
 if get_scanner_owner(t)!="cloudflare" and get_scanner_owner(t)!="UNDECLARED":
  raise RuntimeError("SCANNER_OWNER_ALREADY_NAS_RESTORE_CODE_FIRST")
 if current[VIDEO]==["*/5 * * * *"]:
  emit("SCANNER_CRON_ALREADY_RUNNING",safe_to_continue=True);return
 if current[VIDEO]!=[]:raise RuntimeError("UNEXPECTED_SCANNER_CRON")
 mod().cf_call(t,"PUT",VIDEO,[{"cron":"*/5 * * * *"}])
 restored=snapshot(t)
 if restored[VIDEO]!=["*/5 * * * *"]:raise RuntimeError("SCANNER_CRON_ROLLBACK_NOT_VERIFIED")
 if FREEZE.is_file() and not FREEZE.is_symlink():FREEZE.unlink()
 emit("SCANNER_CRON_ROLLBACK_COMPLETE",scanner_cron=restored[VIDEO],
  alerts_cron=restored[ALERTS],content_cron=restored[CONTENT],owner="cloudflare")

def get_scanner_owner(token):
 s=sel();data=s.read_api(token,f"https://api.cloudflare.com/client/v4/accounts/{s.CF_ACCOUNT}/workers/scripts/{VIDEO}/settings")
 bindings=data.get("bindings") if isinstance(data,dict) else None
 if not isinstance(bindings,list):return "UNKNOWN"
 for b in bindings:
  if isinstance(b,dict) and b.get("name")=="RG_MIGRATION_SCANNER_OWNER" and b.get("type")=="plain_text":
   return str(b.get("text") or "UNKNOWN").lower()
 return "UNDECLARED"
def deploy_guard_precheck():
 allowed()
 t=mod().env_token();current=snapshot(t)
 if current!={VIDEO:[],ALERTS:["* * * * *"],CONTENT:["* * * * *"]}:
  raise RuntimeError("SCANNER_CRON_NOT_SELECTIVELY_PAUSED")
 if not FREEZE.is_file() or FREEZE.is_symlink() or not (OUT/"scanner_original_cron.json").is_file():
  raise RuntimeError("SCANNER_BACKUP_OR_FREEZE_MISSING")
 source,cfg=guard_source()
 targets=(WORKER/"src/quota-entry-v2.js",WORKER/"wrangler.toml")
 if any(p.is_symlink() or not p.is_file() for p in targets):raise RuntimeError("SCANNER_WORKER_SOURCE_MISSING")
 if not shutil.which("docker"):raise RuntimeError("DOCKER_MISSING")
 # Current Cloudflare JS built and shipped as a Worker; locally preserve
 # any existing package/node_modules, but require the pinned files present.
 if not (WORKER/"package.json").is_file():raise RuntimeError("SCANNER_PACKAGE_MISSING")
 return source,cfg,targets,current
def deploy_guard():
 source,cfg,targets,baseline=deploy_guard_precheck()
 t=mod().env_token()
 # If a previous attempt already deployed the guard, reconcile first:
 # do not rebuild/redeploy unnecessarily and preserve Cron changes.
 if get_scanner_owner(t)=="nas":
  actual=snapshot(t)
  if actual!=baseline:raise RuntimeError("CF_GUARD_CRONS_CHANGED")
  save(OUT/"scanner_guard_deployed.json",json.dumps({"verified_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
   "crons":actual,"owner":"nas","readback_only":True})+"\n")
  emit("CF_SCANNER_DO_GUARD_ALREADY_LIVE",owner="nas",crons=actual,
   do_alarm_guard_deployed=True,do_alarm_deletion_log_not_verified=True)
  return
 for f in targets:
  b=OUT/(f.name+".before")
  if not b.exists():save(b,f.read_text("utf-8"))
 for f,value in zip(targets,(source,cfg)):
  import stat
  mode=stat.S_IMODE(f.stat().st_mode)
  save(f,value);os.chmod(f,mode)
 cmd=["docker","run","--rm","--env-file",str(ENV),"-v",str(WORKER)+":/app",
  "-w","/app","node:22-bookworm-slim","sh","-lc",
  "npm install --no-audit --no-fund && node --check src/quota-entry-v2.js && npx wrangler deploy --config wrangler.toml"]
 emit("CF_SCANNER_DO_STOP_DEPLOY_STARTED",source_backups=True,
   alerts_and_content_crons_preserved=True,worker_owner="nas")
 try:p=subprocess.run(cmd,capture_output=True,text=True,timeout=520)
 except (OSError,subprocess.TimeoutExpired):
  emit("CF_SCANNER_DO_STOP_DEPLOY_UNCERTAIN",reason="DOCKER_OR_TIMEOUT",check_remote_before_retry=True);return
 if p.returncode:
  logs=(p.stdout or "")+"\n"+(p.stderr or "")
  low=logs.lower()
  if any(v in low for v in ("quota","rate limit","10011")):reason="CF_QUOTA"
  elif "cannot connect to the docker daemon" in low:reason="DOCKER_DAEMON_UNAVAILABLE"
  elif "error parsing" in low and "env" in low:reason="DEPLOY_ENV_INVALID"
  elif "module not found" in low or "cannot find" in low:reason="NODE_DEPENDENCY_MISSING"
  elif "unauthorized" in low or "authentication" in low:reason="CF_AUTH_DENIED"
  else:reason="WRANGLER_FAILED"
  emit("CF_SCANNER_DO_STOP_DEPLOY_UNCERTAIN",reason=reason,exit_code=p.returncode,
   remote_scanner_owner_verified=False,check_remote_before_retry=True);return
 current=snapshot(t)
 remote_owner=get_scanner_owner(t)
 if current!={VIDEO:[],ALERTS:["* * * * *"],CONTENT:["* * * * *"]} or remote_owner!="nas":
  emit("CF_SCANNER_DO_STOP_UNVERIFIED",owner=remote_owner,crons=current);return
 save(OUT/"scanner_guard_deployed.json",json.dumps({"verified_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "crons":current,"owner":"nas"})+"\n")
 emit("CF_SCANNER_DO_GUARD_DEPLOYED_SELECTIVE",owner="nas",
   scanner_cron=[],alerts_cron=current[ALERTS],content_hub_cron=current[CONTENT],
   do_alarm_guard_deployed=True,do_alarm_deletion_log_not_verified=True,
   next_step="deploy_selective_cloudflare_moderation_owner")
def status():
 allowed()
 t=mod().env_token();live=snapshot(t)
 emit("CF_SELECTIVE_SCANNER_STATUS",owner=get_scanner_owner(t),crons=live,
  freeze=FREEZE.is_file(),scanner_guard_receipt=(OUT/"scanner_guard_deployed.json").is_file(),
  nas_gate=GATE.is_file())
def selftest():
 code='RG_MIGRATION_SCANNER_OWNER = "cloudflare"\ncrons = ["*/5 * * * *"]'
 result=code.replace('"cloudflare"','"nas"').replace('crons = ["*/5 * * * *"]','crons = []')
 assert 'RG_MIGRATION_SCANNER_OWNER = "nas"' in result and 'crons = []' in result
 assert set((VIDEO,ALERTS,CONTENT))==set(("rasha-goodbye-video-scanner","rasha-goodbye-air-alerts","rasha-goodbye-content-hub"))
 emit("CF_SELECTIVE_SCANNER_SELFTEST_PASS",network_calls=0)
if __name__=="__main__":
 try:
  p=argparse.ArgumentParser()
  p.add_argument("mode",choices=("selftest","preflight","stop","guard-precheck","deploy-guard","resume-cron","status"))
  a=p.parse_args().mode
  if a=="selftest":selftest()
  elif a=="preflight":
   result=preflight();emit("CF_SELECTIVE_SCANNER_READY",crons=result,
    source_guard_checked=True)
  elif a=="stop":stop_scanner()
  elif a=="guard-precheck":
   src,config,files,live=deploy_guard_precheck()
   emit("CF_SELECTIVE_SCANNER_GUARD_PRECHECK_PASS",crons=live,
    deploy_image="node:22-bookworm-slim",source_size=len(src),
    original_cron_backup_present=True,deploy_freeze=True,
    no_remote_changes=True,independent_do_alarm_still_active_possible=True)
  elif a=="deploy-guard":deploy_guard()
  elif a=="resume-cron":resume_scanner_cron()
  else:status()
 except Exception as ex:
  msg=str(ex)
  if not re.fullmatch(r"[A-Z0-9_]{3,100}",msg):msg=type(ex).__name__
  emit("BLOCKED",reason=msg)
  sys.exit(1)
