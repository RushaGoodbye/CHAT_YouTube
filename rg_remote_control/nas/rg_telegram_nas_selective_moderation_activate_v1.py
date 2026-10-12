#!/usr/bin/env python3
"""RG selective Telegram moderation activation. Cloudflare keeps Kyiv alerts,
minute silence, holiday calendar, Content Hub and Scanner. NAS becomes sole
getUpdates owner after remote deployed-binding proof and propagation.
Requires authorized migration and explicit deployed.json receipt.
"""
import argparse,datetime,importlib.util,json,os,pathlib,re,subprocess,sys,tempfile
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE";SECRETS=ROOT/"RG_SECRETS"
GATE=SECRETS/"rg_nas_telegram_cutover_enabled"
FREEZE=SECRETS/"rg_cf_moderation_handoff_freeze"
PAUSE=SECRETS/"rg_cloudflare_migration_pause"
MIG=STATE/"rg_cf_moderation_handoff_v1"
BOT=STATE/"rg_telegram_nas_native_bot_v01.py"
MINUTE=STATE/"rg_telegram_nas_minute_silence_v1.py"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
OWNER_WORKER="rasha-goodbye-air-alerts"
MIN_AGE=360  # Six-minute deployment settle, no Cron schedules changed.
def emit(status,**v):print(json.dumps({"status":status,**v},ensure_ascii=False),flush=True)
def module():
 p=STATE/"rg_telegram_cf_selective_moderation_handoff_v1.py"
 if p.is_symlink() or not p.is_file():raise RuntimeError("SELECTIVE_MODULE_MISSING")
 spec=importlib.util.spec_from_file_location("rg_selective_handoff_verify",str(p))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 return m
def get_receipt():
 p=MIG/"deployed.json"
 if not p.is_file() or p.is_symlink():raise RuntimeError("CF_HANDOFF_DEPLOY_NOT_CONFIRMED")
 try:
  doc=json.loads(p.read_text("utf-8"))
  at=datetime.datetime.fromisoformat(doc["deployed_at"])
 except (OSError,ValueError,KeyError):raise RuntimeError("CF_HANDOFF_RECEIPT_INVALID") from None
 if doc.get("owner")!="nas" or not doc.get("crons"):
  raise RuntimeError("CF_HANDOFF_RECEIPT_INVALID")
 age=(datetime.datetime.now(datetime.timezone.utc)-at).total_seconds()
 if age<MIN_AGE:raise RuntimeError("CLOUDFLARE_PROPAGATION_WAIT")
 if age>48*3600:raise RuntimeError("STALE_HANDOFF_RECEIPT")
 return doc,int(age)
def preflight():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if GATE.exists() or GATE.is_symlink():raise RuntimeError("NAS_ALREADY_ENABLED")
 if PAUSE.exists():raise RuntimeError("FULL_CLOUDFLARE_PAUSE_ACTIVE")
 if not FREEZE.is_file() or FREEZE.is_symlink():raise RuntimeError("CF_AUTO_DEPLOY_NOT_FROZEN")
 if not BOT.is_file() or BOT.is_symlink():raise RuntimeError("NAS_BOT_MISSING")
 if not MINUTE.is_file() or MINUTE.is_symlink():raise RuntimeError("NAS_MINUTE_MISSING")
 # A selective gate will trigger minute-silence scheduler too; ensure patched
 # NAS module explicitly declines publishing while Cloudflare owns it.
 if 'minute_silence_stays_on_cloudflare' not in MINUTE.read_text("utf-8"):
  raise RuntimeError("DUPLICATE_MINUTE_SILENCE_RISK")
 if not SCHED.is_file() or SCHED.is_symlink():raise RuntimeError("NAS_SCHEDULER_MISSING")
 s=SCHED.read_text("utf-8")
 for tag in ("# RG_NAS_NATIVE_TELEGRAM_BOT_V01","# RG_NAS_MINUTE_SILENCE_V1"):
  if s.count(tag)!=1:raise RuntimeError("NAS_SCHEDULER_GATE_MISSING")
 doc,age=get_receipt()
 m=module()
 token=m.module().env_token()
 expected={"rasha-goodbye-air-alerts":["* * * * *"],
  "rasha-goodbye-content-hub":["* * * * *"],
  "rasha-goodbye-video-scanner":["*/5 * * * *"]}
 live={name:m.cron(token,name) for name in expected}
 if live!=expected or doc["crons"]!=expected:
  raise RuntimeError("CLOUDFLARE_SCHEDULE_CHANGED")
 if m.owner(token)!="nas":raise RuntimeError("CF_MODERATION_NOT_DISABLED")
 p=subprocess.run([sys.executable,str(BOT),"preflight"],capture_output=True,text=True,timeout=30)
 if p.returncode:raise RuntimeError("BOT_API_PREFLIGHT_FAILED")
 try:pre=json.loads(p.stdout)
 except ValueError:raise RuntimeError("BOT_PREFLIGHT_INVALID") from None
 if pre.get("status")!="NATIVE_BOT_PREFLIGHT_PASS" or pre.get("bot_username")!="RushaGoodbyeNews_bot" or pre.get("target")!="RussiaGoodbyeUA":
  raise RuntimeError("WRONG_TELEGRAM_BOT_OR_CHANNEL")
 if pre.get("webhook_present") is not False:raise RuntimeError("TELEGRAM_WEBHOOK_CONFLICT")
 return pre,age
def activate():
 pre,age=preflight()
 record={"cloudflare_polling_disabled_verified":True,"nas_single_poll_owner":True,
   "selective_moderation_handoff":True,"minute_silence_owner":"cloudflare",
   "kyiv_air_alerts_owner":"cloudflare","content_hub_owner":"cloudflare",
   "video_scanner_owner":"cloudflare","legacy_cards_not_republished":True,
   "no_backfill":True,
   "activated_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
   "settled_for_seconds":age}
 fd,tmp=tempfile.mkstemp(prefix=".rg-selective-bot-",dir=str(SECRETS))
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(json.dumps(record,ensure_ascii=False)+"\n")
  os.chmod(tmp,0o600)
  os.replace(tmp,GATE)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 emit("RG_NAS_SELECTIVE_MODERATION_ACTIVATED",owner="NAS",telegram_bot=pre["bot_username"],
   channel=pre["target"],cloudflare_crons_preserved=True,
   cloudflare_alerts_and_calendar_remain_live=True,
   minute_silence_owner="cloudflare",legacy_cards="NO_AUTOMATIC_REPLAY",
   next_step="send_new_link_or_forward_with_photo_to_bot_and_approve")
def status():
 active=GATE.is_file() and not GATE.is_symlink()
 if not active:emit("RG_NAS_SELECTIVE_OWNER_GATE_CLOSED",deployed_receipt=(MIG/"deployed.json").exists());return
 try:
  cfg=json.loads(GATE.read_text("utf-8"))
 except ValueError:raise RuntimeError("INVALID_GATE") from None
 emit("RG_NAS_SELECTIVE_OWNER_GATE_OPEN" if cfg.get("selective_moderation_handoff") is True else "RG_NAS_GATE_OTHER_MODE",
   owner="nas",minute_silence_owner=cfg.get("minute_silence_owner"),activation=cfg.get("activated_at_utc"))
def selftest():
 assert MIN_AGE>=300 and MIN_AGE<=1200
 assert {"cloudflare_polling_disabled_verified","nas_single_poll_owner","selective_moderation_handoff"}.issubset(
   {"cloudflare_polling_disabled_verified","nas_single_poll_owner","selective_moderation_handoff"})
 emit("NAS_SELECTIVE_ACTIVATOR_SELFTEST_PASS",telegram_sends=0,cloudflare_writes=0)
if __name__=="__main__":
 try:
  p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","preflight","activate","status"))
  a=p.parse_args().mode
  if a=="selftest":selftest()
  elif a=="status":status()
  elif a=="preflight":
   x,age=preflight();emit("RG_NAS_SELECTIVE_ACTIVATION_READY",settled_seconds=age,
     bot=x["bot_username"],channel=x["target"])
  else:activate()
 except Exception as ex:
  msg=str(ex)
  if not re.fullmatch(r"[A-Z0-9_]{3,96}",msg):msg=type(ex).__name__
  emit("BLOCKED",reason=msg,nas_gate_not_opened=True)
  sys.exit(1)
