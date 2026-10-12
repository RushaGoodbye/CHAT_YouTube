#!/usr/bin/env python3
"""Selective Cloudflare->NAS Telegram moderation handoff, preserving alerts,
minute silence, scheduled Content Hub, and Video Scanner Cron/DO.
Never opens NAS gate: that requires separate independently verified activation.
Commands: selftest, preflight, deploy, status, rollback.
"""
import argparse,datetime,importlib.util,json,os,pathlib,re,shutil,subprocess,sys,tempfile,urllib.error,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SECRETS=ROOT/"RG_SECRETS"
TARGET=ROOT/"RG_ALERTS_DEPLOY/cloudflare-alerts"
ENV=ROOT/"RG_ALERTS_DEPLOY/deploy.env"
DEPLOYER=ROOT/"RG_NAS_AUTO_DEPLOY.sh"
OUT=STATE/"rg_cf_moderation_handoff_v1"
PAUSE=SECRETS/"rg_cloudflare_migration_pause"
CUTOVER=SECRETS/"rg_nas_telegram_cutover_enabled"
FREEZE=SECRETS/"rg_cf_moderation_handoff_freeze"
CF_ACCOUNT="be73f73dbe2a5471c62384dc673c91e6"
WORKER="rasha-goodbye-air-alerts"
OTHER=("rasha-goodbye-content-hub","rasha-goodbye-video-scanner")
MARKER="# RG_NAS_SELECTIVE_MODERATION_FREEZE_V1"
ANCHOR="acquire_deploy_lock\nnote_owner_state RUNNING"
OLD_CALL="const moderationTask = processTelegramModerationUpdates(env)"
NEW_CALL='''// RG NAS selective moderation cutover V1: preserve Kyiv alerts and calendar.
      const moderationOwner = String(env.RG_MODERATION_RUNTIME_OWNER || "cloudflare").trim().toLowerCase();
      const moderationTask = (moderationOwner === "nas"
        ? Promise.resolve({ ok: true, skipped: "nas_moderation_owner", owner: "nas", polls: 0 })
        : processTelegramModerationUpdates(env))'''
GUARD='''# RG_NAS_SELECTIVE_MODERATION_FREEZE_V1
# Do not silently redeploy legacy Cloudflare polling after NAS takes ownership.
if [ -f "$ROOT/RG_SECRETS/rg_cf_moderation_handoff_freeze" ]; then
  note_owner_state PAUSED_SELECTIVE_MODERATION_HANDOFF
  printf '%s\n' "RG_NAS_CF_AUTO_DEPLOY_FROZEN_FOR_MODERATION"
  exit 0
fi

'''
def out(status,**x):
 print(json.dumps({"status":status,"native_poll_started":False,
  "channel_sends":0,**x},ensure_ascii=False),flush=True)
def module():
 path=STATE/"rg_telegram_cf_cron_pause_v1.py"
 if not path.is_file() or path.is_symlink():raise RuntimeError("CF_API_HELPER_MISSING")
 spec=importlib.util.spec_from_file_location("rg_pause_read_helper",str(path))
 obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
 return obj
def read_api(token,url):
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"User-Agent":"RG-NAS-Selective-Owner/1"})
 try:
  with urllib.request.urlopen(req,timeout=9) as r:data=json.loads(r.read(131072))
 except urllib.error.HTTPError as e:raise RuntimeError("CF_HTTP_"+str(e.code)) from None
 except (urllib.error.URLError,OSError,TimeoutError):
  data=module().cf_get_ipv4_curl(token,url,WORKER)
 except ValueError:raise RuntimeError("CF_RESPONSE_INVALID") from None
 if not isinstance(data,dict) or data.get("success") is not True:
  raise RuntimeError("CF_API_REJECTED")
 return data.get("result")
def cron(token,name):
 data=read_api(token,f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/workers/scripts/{name}/schedules")
 if not isinstance(data,dict) or not isinstance(data.get("schedules"),list):
  raise RuntimeError("CF_CRON_RESPONSE_INVALID")
 vals=data["schedules"]
 if not all(isinstance(z,dict) and isinstance(z.get("cron"),str) for z in vals):
  raise RuntimeError("CF_CRON_BAD_ITEM")
 return [v["cron"] for v in vals]
def owner(token):
 data=read_api(token,f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/workers/scripts/{WORKER}/settings")
 bindings=data.get("bindings") if isinstance(data,dict) else None
 if not isinstance(bindings,list):return "UNKNOWN"
 for b in bindings:
  if b.get("name")=="RG_MODERATION_RUNTIME_OWNER" and b.get("type")=="plain_text":
   return str(b.get("text") or "UNKNOWN").lower()
 return "UNDECLARED"
def patch_source(code,config):
 if 'moderationOwner === "nas"' in code and "nas_moderation_owner" in code:
  patched_code=code
  mode="ALREADY_GUARDED"
 else:
  if code.count(OLD_CALL)!=1:raise RuntimeError("LEGACY_MODERATION_CALL_NOT_UNIQUE")
  patched_code=code.replace(OLD_CALL,NEW_CALL,1)
  mode="PATCHED"
 if "const alertPollTask = poll(env, ctx)" not in patched_code:raise RuntimeError("KYIV_ALERT_CONTRACT_NOT_FOUND")
 if "maybePublishMinuteSilence(env, ctx, event?.scheduledTime)" not in patched_code:
  raise RuntimeError("MINUTE_SILENCE_CONTRACT_NOT_FOUND")
 if "await Promise.all([alertPollTask, silenceTask]);" not in patched_code:
  raise RuntimeError("SAFETY_HEAD_START_CHANGED")
 if '[vars]' not in config:raise RuntimeError("WRANGLER_VARS_MISSING")
 if 'name = "rasha-goodbye-air-alerts"' not in config:raise RuntimeError("WRONG_ALERT_WORKER")
 if 'crons = ["* * * * *"]' not in config:raise RuntimeError("ALERT_CRON_MUST_REMAIN")
 if 'RG_MODERATION_RUNTIME_OWNER = "cloudflare"' in config:
  patched_cfg=config.replace('RG_MODERATION_RUNTIME_OWNER = "cloudflare"',
    'RG_MODERATION_RUNTIME_OWNER = "nas"')
 elif 'RG_MODERATION_RUNTIME_OWNER = "nas"' in config:
  patched_cfg=config
 elif 'RG_MODERATION_RUNTIME_OWNER' not in config:
  key='TELEGRAM_CHAT_ID = "@RussiaGoodbyeUA"'
  if config.count(key)!=1:raise RuntimeError("TELEGRAM_CHANNEL_VAR_NOT_FOUND")
  patched_cfg=config.replace(key,key+'\nRG_MODERATION_RUNTIME_OWNER = "nas"',1)
 else:raise RuntimeError("MODERATION_OWNER_CONFIG_UNEXPECTED")
 if patched_cfg.count('RG_MODERATION_RUNTIME_OWNER = "nas"')!=1:
  raise RuntimeError("MODERATION_OWNER_CONFIG_INVALID")
 return patched_code,patched_cfg,mode
def deployer_patch(code):
 if code.count(MARKER)==1:return code,"ALREADY_GUARDED"
 if code.count(MARKER)>1:raise RuntimeError("DEPLOYER_GUARD_DUPLICATED")
 if code.count(ANCHOR)!=1:raise RuntimeError("DEPLOYER_ANCHOR_MISSING")
 return code.replace(ANCHOR,GUARD+ANCHOR,1),"PATCHED"
def syntax_shell(source):
 p=subprocess.run(["/bin/sh","-n"],input=source,text=True,capture_output=True,timeout=5)
 if p.returncode:raise RuntimeError("DEPLOYER_SHELL_INVALID")
def sources():
 files=(TARGET/"src/index.js",TARGET/"wrangler.toml")
 if any(p.is_symlink() or not p.is_file() for p in files):raise RuntimeError("ALERT_SOURCE_MISSING")
 return files
def prerequisites(allow_frozen=False):
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if PAUSE.exists():raise RuntimeError("ALL_CLOUDFLARE_CRONS_PAUSED_REFUSE_SELECTIVE")
 if CUTOVER.exists():raise RuntimeError("NAS_GATE_ALREADY_ACTIVE")
 if FREEZE.exists() and not allow_frozen:raise RuntimeError("SELECTIVE_OWNER_FREEZE_ALREADY_PRESENT")
 if not ENV.is_file() or ENV.is_symlink():raise RuntimeError("ALERT_DEPLOY_CREDENTIALS_MISSING")
 if not (STATE/"rg_telegram_nas_native_bot_v01.py").is_file():
  raise RuntimeError("NAS_MODERATION_BOT_MISSING")
 if not DEPLOYER.is_file() or DEPLOYER.is_symlink():raise RuntimeError("AUTODEPLOY_SCRIPT_MISSING")
 if (ROOT/"RG_NAS_STATE/deploy.lock").exists():raise RuntimeError("AUTO_DEPLOY_IN_PROGRESS")
 f=sources()
 original=(f[0].read_text("utf-8"),f[1].read_text("utf-8"))
 patched=patch_source(*original)
 before=DEPLOYER.read_text("utf-8")
 new,mode=deployer_patch(before);syntax_shell(new)
 return f,original,patched,new,mode
def check():
 files,original,patched,deployercode,mode=prerequisites(allow_frozen=True)
 cf=module()
 t=cf.env_token()
 sc={n:cron(t,n) for n in (WORKER,)+OTHER}
 if sc[WORKER]!=["* * * * *"] or sc["rasha-goodbye-content-hub"]!=["* * * * *"] or sc["rasha-goodbye-video-scanner"]!=["*/5 * * * *"]:
  raise RuntimeError("CF_SCHEDULES_NOT_ORIGINAL")
 current=owner(t)
 if current not in ("cloudflare","nas","UNDECLARED"):
  raise RuntimeError("CF_OWNER_UNKNOWN")
 return files,original,patched,deployercode,mode,sc,current
def save(path,data):
 if path.is_symlink():raise RuntimeError("SYMLINK_REFUSED")
 fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix=".rg-selective-")
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(data)
  os.chmod(tmp,0o600)
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def ensure_backup(original,deployer):
 if OUT.is_symlink():raise RuntimeError("BACKUP_SYMLINK")
 OUT.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(OUT,0o700)
 names=("index.js.before","wrangler.toml.before","RG_NAS_AUTO_DEPLOY.sh.before")
 vals=(original[0],original[1],deployer)
 for name,value in zip(names,vals):
  dest=OUT/name
  if dest.exists() and dest.read_text("utf-8")!=value:
   raise RuntimeError("EXISTING_BACKUP_DIFFERS")
  if not dest.exists():save(dest,value)
def stop_auto_deploy(deployer):
 if MARKER in deployer:return
 old=DEPLOYER.read_text("utf-8")
 changed,mode=deployer_patch(old)
 if mode!="PATCHED":return
 syntax_shell(changed)
 import stat
 modebits=stat.S_IMODE(DEPLOYER.stat().st_mode)
 save(DEPLOYER,changed)
 os.chmod(DEPLOYER,modebits)
def do_deploy():
 files,original,patched,dep,guard,sc,owner_before=check()
 if owner_before=="nas":raise RuntimeError("CLOUDFLARE_ALREADY_OWNED_BY_NAS")
 if FREEZE.exists():raise RuntimeError("SELECTIVE_FREEZE_ALREADY_PRESENT")
 ensure_backup(original,DEPLOYER.read_text("utf-8"))
 stop_auto_deploy(dep)
 save(FREEZE,json.dumps({"purpose":"selective Telegram moderation cutover",
   "created":datetime.datetime.now(datetime.timezone.utc).isoformat()})+"\n")
 for file,text in zip(files,patched[:2]):
  import stat
  modebits=stat.S_IMODE(file.stat().st_mode)
  save(file,text);os.chmod(file,modebits)
 if not shutil.which("docker"):raise RuntimeError("DOCKER_MISSING_FROZEN")
 cmd=["docker","run","--rm","--env-file",str(ENV),"-v",str(TARGET)+":/app",
      "-w","/app","node:22-bookworm-slim","sh","-lc",
      "npm install --no-audit --no-fund && node --check src/index.js && npx wrangler deploy --config wrangler.toml"]
 out("CF_SELECTIVE_DEPLOY_STARTED",source_backed_up=True,auto_deploy_frozen=True,
   air_alerts_cron_preserved=True,content_cron_preserved=True,scanner_cron_preserved=True)
 try:
  p=subprocess.run(cmd,text=True,capture_output=True,timeout=520)
 except (OSError,subprocess.TimeoutExpired):
  out("CF_SELECTIVE_DEPLOY_UNCERTAIN",reason="DEPLOY_FAILED_OR_TIMED_OUT",
      next_step="status_and_reconciliation_required")
  return
 if p.returncode:
  logs=(p.stdout or "")+"\n"+(p.stderr or "")
  reason="CF_QUOTA" if any(x in logs.lower() for x in ("quota","rate limit","10011")) else "WRANGLER_FAILED"
  out("CF_SELECTIVE_DEPLOY_UNCERTAIN",reason=reason,
      exit_code=p.returncode,next_step="status_and_reconciliation_required")
  return
 try:
  after=owner(module().env_token())
  schedule={n:cron(module().env_token(),n) for n in (WORKER,)+OTHER}
 except RuntimeError:
  out("CF_SELECTIVE_DEPLOY_UNVERIFIED",reason="REMOTE_READBACK_FAILED")
  return
 if after!="nas" or schedule!=sc:
  out("CF_SELECTIVE_DEPLOY_UNVERIFIED",owner=after,
      cron_unchanged=schedule==sc)
  return
 save(OUT/"deployed.json",json.dumps({"deployed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "owner":"nas","crons":sc},ensure_ascii=False)+"\n")
 out("CF_SELECTIVE_MODERATION_HANDOFF_DEPLOYED",owner="nas",
   cron_unchanged=True,native_gate_still_closed=True,
   alert_and_content_jobs_remain_active=True,
   next_step="selective_nas_activation_after_propagation")
def status():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 t=module().env_token()
 sc={n:cron(t,n) for n in (WORKER,)+OTHER}
 out("CF_SELECTIVE_MODERATION_STATUS",owner=owner(t),crons=sc,
    freeze=FREEZE.is_file(),deployment_receipt=(OUT/"deployed.json").is_file(),
    bot_gate=CUTOVER.is_file())
def selftest():
 initial='''const alertPollTask = poll(env, ctx); maybePublishMinuteSilence(env, ctx, event?.scheduledTime);
  await Promise.all([alertPollTask, silenceTask]); const moderationTask = processTelegramModerationUpdates(env)
  .then((moderation) => console.log(moderation));'''
 config='''name = "rasha-goodbye-air-alerts"\n[triggers]\ncrons = ["* * * * *"]\n[vars]\nTELEGRAM_CHAT_ID = "@RussiaGoodbyeUA"\n'''
 changed,cfg,mode=patch_source(initial,config)
 assert mode=="PATCHED" and "nas_moderation_owner" in changed
 assert 'RG_MODERATION_RUNTIME_OWNER = "nas"' in cfg
 assert patch_source(changed,cfg)[2]=="ALREADY_GUARDED"
 d='#!/bin/sh\nROOT="/volume1/docker"\nnote_owner_state() { :; }\nacquire_deploy_lock\nnote_owner_state RUNNING\n'
 new,mode=deployer_patch(d)
 assert mode=="PATCHED" and deployer_patch(new)[1]=="ALREADY_GUARDED"
 syntax_shell(new)
 out("CF_SELECTIVE_HANDOFF_SELFTEST_PASS",read_only=True,telegram_sends=0,
     preserves_alerts=True,preserves_calendar=True,preserves_scanner=True)
if __name__=="__main__":
 try:
  a=argparse.ArgumentParser();a.add_argument("mode",choices=("selftest","preflight","deploy","status"))
  arg=a.parse_args().mode
  if arg=="selftest":selftest()
  elif arg=="preflight":
   result=check()
   out("CF_SELECTIVE_HANDOFF_READY",owner=result[-1],worker_crons=result[-2],
       patch_mode=result[2][2],deployer_guard=result[4],
       no_remote_changes=True)
  elif arg=="deploy":do_deploy()
  else:status()
 except Exception as ex:
  msg=str(ex)
  if not re.fullmatch(r"[A-Z0-9_]{3,110}",msg):msg=type(ex).__name__
  out("BLOCKED",reason=msg)
  sys.exit(1)
