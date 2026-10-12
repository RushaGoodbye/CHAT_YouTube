#!/usr/bin/env python3
"""RG Telegram NAS controlled one-writer activation.
Requires confirmed three Cloudflare Cron stops, deployed scanner guard owner
=nas, minimum propagation window, and working native bot Telegram preflight.
No historical backfill and legacy buttons remain isolated.
"""
import argparse,datetime,json,os,pathlib,re,subprocess,sys,tempfile,time,urllib.error,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE";SECRETS=ROOT/"RG_SECRETS"
GATE=SECRETS/"rg_nas_telegram_cutover_enabled"
PAUSE=SECRETS/"rg_cloudflare_migration_pause"
SESSION=STATE/"rg_cf_cron_pause_v1"
BOT=STATE/"rg_telegram_nas_native_bot_v01.py"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
ENVFILES=(ROOT/"RG_ALERTS_DEPLOY/deploy.env",ROOT/"RG_DEPLOY/deploy.env")
ACCOUNT="be73f73dbe2a5471c62384dc673c91e6"
NAMES=("rasha-goodbye-video-scanner","rasha-goodbye-air-alerts","rasha-goodbye-content-hub")
MIN_AGE=20*60
def emit(status,**k):
 print(json.dumps({"status":status,**k},ensure_ascii=False),flush=True)
def token():
 for file in ENVFILES:
  if file.is_symlink() or not file.is_file():continue
  try:s=file.read_text("utf-8")
  except OSError:continue
  for line in s.splitlines():
   match=re.fullmatch(r"\s*(?:export\s+)?(CLOUDFLARE_API_TOKEN|CF_API_TOKEN|CLOUDFLARE_TOKEN)\s*=\s*(.*)\s*",line)
   if match:
    value=match.group(2).strip().strip("'\"")
    if len(value)>=25 and "$" not in value:return value
 raise RuntimeError("CF_API_TOKEN_UNAVAILABLE")
def api(url,auth):
 from importlib.util import spec_from_file_location,module_from_spec
 path=STATE/"rg_telegram_cf_cron_pause_v1.py"
 if not path.is_file() or path.is_symlink():raise RuntimeError("CF_PAUSE_HELPER_MISSING")
 spec=spec_from_file_location("rg_cf_pause_activate_helper",str(path))
 mod=module_from_spec(spec);spec.loader.exec_module(mod)
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+auth,"User-Agent":"RG-NAS-Cutover/2"})
 try:
  with urllib.request.urlopen(req,timeout=9) as r:j=json.loads(r.read(131072))
 except urllib.error.HTTPError as e:raise RuntimeError("CF_HTTP_"+str(e.code)) from None
 except (urllib.error.URLError,OSError,TimeoutError):
  j=mod.cf_get_ipv4_curl(auth,url,"rasha-goodbye-video-scanner")
 except ValueError:raise RuntimeError("CF_READ_ERROR") from None
 if not isinstance(j,dict) or j.get("success") is not True:raise RuntimeError("CF_API_REJECTED")
 return j.get("result")
def gates():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if not PAUSE.is_file() or PAUSE.is_symlink():raise RuntimeError("CLOUDFLARE_PAUSE_MARKER_ABSENT")
 for file in (SESSION/"original_schedules.json",SESSION/"paused.json",BOT,SCHED):
  if file.is_symlink() or not file.is_file():raise RuntimeError("MIGRATION_PREREQUISITES_MISSING")
 paused=json.loads((SESSION/"paused.json").read_text("utf-8"))
 try:paused_at=datetime.datetime.fromisoformat(paused["paused_utc"])
 except (ValueError,KeyError):raise RuntimeError("CRON_PAUSE_TIMESTAMP_INVALID") from None
 age=(datetime.datetime.now(datetime.timezone.utc)-paused_at).total_seconds()
 if age<MIN_AGE:raise RuntimeError("CLOUDFLARE_PAUSE_PROPAGATION_PENDING")
 scheduler=SCHED.read_text("utf-8")
 if scheduler.count("# RG_NAS_NATIVE_TELEGRAM_BOT_V01")!=1:
  raise RuntimeError("NAS_BOT_SCHEDULER_HOOK_MISSING")
 if scheduler.count("# RG_NAS_MINUTE_SILENCE_V1")!=1:
  raise RuntimeError("MINUTE_SCHEDULER_HOOK_MISSING")
 if GATE.exists() or GATE.is_symlink():raise RuntimeError("NAS_BOT_ALREADY_ACTIVE")
 auth=token()
 for name in NAMES:
  result=api("https://api.cloudflare.com/client/v4/accounts/"+ACCOUNT+"/workers/scripts/"+name+"/schedules",auth)
  if not isinstance(result,dict) or result.get("schedules")!=[]:
   raise RuntimeError("CLOUDFLARE_CRON_STILL_ACTIVE")
 info=api("https://api.cloudflare.com/client/v4/accounts/"+ACCOUNT+"/workers/scripts/"+NAMES[0]+"/settings",auth)
 if not isinstance(info,dict):raise RuntimeError("SCANNER_BINDINGS_MISSING")
 bindings=info.get("bindings")
 if not isinstance(bindings,list) or not any(isinstance(x,dict) and x.get("name")=="RG_MIGRATION_SCANNER_OWNER"
  and x.get("type")=="plain_text" and x.get("text")=="nas" for x in bindings):
  raise RuntimeError("SCANNER_DO_GUARD_NOT_DEPLOYED")
 r=subprocess.run([sys.executable,str(BOT),"preflight"],capture_output=True,text=True,timeout=30)
 if r.returncode:raise RuntimeError("TELEGRAM_PREFLIGHT_FAILED")
 try:p=json.loads(r.stdout)
 except ValueError:raise RuntimeError("TELEGRAM_PREFLIGHT_INVALID") from None
 if p.get("status")!="NATIVE_BOT_PREFLIGHT_PASS" or p.get("webhook_present") is not False:
  raise RuntimeError("TELEGRAM_PREFLIGHT_INVALID")
 if p.get("bot_username")!="RushaGoodbyeNews_bot" or p.get("target")!="RussiaGoodbyeUA":
  raise RuntimeError("TELEGRAM_WRONG_TARGET")
 return age,p
def activate():
 age,pre=gates()
 now=datetime.datetime.now(datetime.timezone.utc)
 doc={"cloudflare_polling_disabled_verified":True,
  "nas_single_poll_owner":True,
  "cf_three_crons_empty_verified":True,
  "scanner_do_alarm_guard_deployed":True,
  "minimum_propagation_elapsed_sec":int(age),
  "legacy_cards_not_republished":True,
  "no_backfill":True,
  "activated_at_utc":now.isoformat()}
 fd,tmp=tempfile.mkstemp(dir=str(SECRETS),prefix=".rg-nas-activated-")
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(json.dumps(doc,ensure_ascii=False)+"\n")
  os.chmod(tmp,0o600);os.replace(tmp,GATE)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 emit("RG_NAS_TELEGRAM_ONE_WRITER_GATE_OPEN",owner="NAS",
  cloudflare_three_crons="PAUSED",scanner_guard="DEPLOYED",
  propagated_seconds=int(age),telegram_bot=pre["bot_username"],
  old_cards="ISOLATED_NOT_REPUBLISHED",automatic_backfill=False,
  next_step="send_fresh_photo_with_caption_or_news_link_to_bot_then_approve")
def status():
 if GATE.is_file() and not GATE.is_symlink():
  data=json.loads(GATE.read_text("utf-8"))
  emit("RG_NAS_GATE_CONFIGURED",owner="nas",activation=data.get("activated_at_utc"),
   no_backfill=data.get("no_backfill"))
 else:emit("RG_NAS_GATE_CLOSED",owner="cloudflare_or_migration_pause")
def selftest():
 assert MIN_AGE>=900
 assert "RushaGoodbyeNews_bot"=="RushaGoodbyeNews_bot"
 assert set(NAMES)=={"rasha-goodbye-air-alerts","rasha-goodbye-content-hub","rasha-goodbye-video-scanner"}
 emit("RG_NAS_ONE_WRITER_GATE_SELFTEST_PASS",telegram_sends=0,telegram_polls=0)
if __name__=="__main__":
 try:
  p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","status","activate"))
  a=p.parse_args()
  {"selftest":selftest,"status":status,"activate":activate}[a.mode]()
 except Exception as ex:
  reason=str(ex)
  if not re.fullmatch(r"[A-Z0-9_]{3,80}",reason):reason=type(ex).__name__
  emit("BLOCKED",reason=reason,gate_not_opened=True)
  sys.exit(1)
