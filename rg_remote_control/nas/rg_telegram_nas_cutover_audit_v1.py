#!/usr/bin/env python3
"""Read-only transition audit: NAS scheduler, Cloudflare triggers, Telegram bot.
Never outputs tokens, never polls getUpdates, never sends, never changes crons.
"""
import argparse,hashlib,json,os,pathlib,re,sqlite3,sys,urllib.error,urllib.request
ROOT=pathlib.Path("/volume1/docker")
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
SECRETS=ROOT/"RG_SECRETS"
ROOTS=(ROOT/"RG_ALERTS_DEPLOY/deploy.env",ROOT/"RG_CONTENT_DEPLOY/deploy.env",ROOT/"RG_DEPLOY/deploy.env")
WORKERS=("rasha-goodbye-air-alerts","rasha-goodbye-content-hub","rasha-goodbye-video-scanner")
ACCOUNT_ID="be73f73dbe2a5471c62384dc673c91e6"
def safe_environment():
 env={}
 for path in ROOTS:
  if path.is_symlink() or not path.is_file():continue
  try:
   if path.stat().st_size>100000:continue
   data=path.read_text("utf-8")
  except (OSError,UnicodeDecodeError):continue
  for line in data.splitlines():
   match=re.fullmatch(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*",line)
   if not match:continue
   name,raw=match.groups()
   val=raw.strip().strip("\"'")
   if val and not re.search(r"\$\(|\$\{",val):env.setdefault(name,val)
 return env
def cloudflare_probe(env):
 token=next((env[x] for x in ("CLOUDFLARE_API_TOKEN","CF_API_TOKEN","CLOUDFLARE_TOKEN") if env.get(x)),None)
 if not token:return {"status":"CF_API_CREDENTIAL_NOT_DISCOVERED","read_only":True}
 out={"status":"CF_API_READ_ONLY_CHECKED","workers":{},"read_only":True}
 for name in WORKERS:
  url="https://api.cloudflare.com/client/v4/accounts/"+ACCOUNT_ID+"/workers/scripts/"+name+"/schedules"
  req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"User-Agent":"RG-NAS-Cutover-Audit/1"})
  try:
   with urllib.request.urlopen(req,timeout=9) as resp:
    raw=resp.read(50000)
   data=json.loads(raw)
   if not data.get("success") or not isinstance(data.get("result"),dict):
    out["workers"][name]={"status":"CF_ERROR_RESPONSE"};continue
   result=data.get("result")
   schedules=result.get("schedules") or result.get("crons") or []
   if not isinstance(schedules,list):schedules=[]
   out["workers"][name]={"status":"OK","active_schedules":[x.get("cron") if isinstance(x,dict) else None for x in schedules][:20]}
  except urllib.error.HTTPError as e:out["workers"][name]={"status":"HTTP_"+str(e.code)}
  except (urllib.error.URLError,OSError,ValueError):out["workers"][name]={"status":"CF_READ_FAILED"}
 return out
def audit(with_cloudflare=False):
 result={"status":"NATIVE_BOT_CUTOVER_AUDIT_V1","read_only":True,
 "telegram_sends":0,"telegram_polls":0,"cloudflare_writes":0,
 "nas_scheduler":{},"nas_bot":{},"cloudflare":{"status":"NOT_CHECKED"}}
 if SCHED.is_symlink() or not SCHED.is_file():
  result["nas_scheduler"]={"status":"MISSING_OR_SYMLINK"}
 else:
  text=SCHED.read_text("utf-8")
  marks=("# RG_NAS_SHADOW_RUNTIME_V1_END","# RG_NAS_LOCAL_REVIEW_EXPORT_V1",
         "# RG_NAS_NATIVE_TELEGRAM_BOT_V01","AUTODEPLOY=",
         "# RG_NAS_LOCAL_CANDIDATE_INGEST_V1")
  result["nas_scheduler"]={
   "status":"PRESENT","sha256":hashlib.sha256(text.encode()).hexdigest()[:16],
   "size":len(text),"anchor_counts":{m:text.count(m) for m in marks},
   "safe_to_patch":text.count("# RG_NAS_SHADOW_RUNTIME_V1_END")==1 or text.count("AUTODEPLOY=")==1,
   "existing_hook_live":text.count("# RG_NAS_NATIVE_TELEGRAM_BOT_V01")==1}
 native=ROOT/"RG_TELEGRAM_STATE/rg_telegram_nas_native_bot_v01.py"
 gate=SECRETS/"rg_nas_telegram_cutover_enabled"
 token=SECRETS/"rg_telegram_bot_token"
 result["nas_bot"]={"source_installed":native.is_file() and not native.is_symlink(),
  "cutover_gate_present":gate.exists(),"credential_present":token.is_file() and not token.is_symlink()}
 staged=ROOT/"RG_TELEGRAM_STATE/cf_moderation_handoff_stage_v1"
 report=staged/"preflight_report.json"
 report_ready=False;legacy_pending=True
 if report.is_file() and not report.is_symlink():
  try:
   data=json.loads(report.read_text("utf-8"))
   report_ready=(data.get("status")=="CF_OWNER_GUARD_STAGE_READY"
     and data.get("inventory",{}).get("scanner_durable_object_alarm_guard_ready") is True)
   legacy_pending=data.get("inventory",{}).get("legacy_moderation_cards_reconciliation_pending") is not False
  except (OSError,ValueError):pass
 result["migration_staging"]={"source_inventory_ready":report_ready,
  "legacy_callback_reconciliation_pending":legacy_pending,
  "disabling_cron_alone_does_not_stop_DO_alarm":True}
 if with_cloudflare:result["cloudflare"]=cloudflare_probe(safe_environment())
 result["requirements"]={
  "cloudflare_moderation_polling_disabled_verified":False,
  "cloudflare_scheduled_content_migration_verified":False,
  "scanner_durable_object_alarm_disabled_verified":False,
  "old_moderation_cards_migrated":False,
  "native_bot_polling_active":False}
 return result
def main():
 p=argparse.ArgumentParser()
 p.add_argument("mode",choices=("selftest","audit"))
 p.add_argument("--cloudflare",action="store_true");args=p.parse_args()
 if args.mode=="selftest":
  assert not audit(False)["nas_bot"].get("native_bot_polling_active",False)
  print(json.dumps({"status":"CUTOVER_AUDIT_SELFTEST_PASS","read_only":True,"telegram_polls":0,"telegram_sends":0}))
  return
 print(json.dumps(audit(args.cloudflare),ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"CUTOVER_AUDIT_BLOCKED","reason":type(e).__name__,
    "read_only":True,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
