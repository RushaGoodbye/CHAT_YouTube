#!/usr/bin/env python3
"""Read-only batch report for Cloudflare-to-NAS moderation ownership.
Does not call Telegram getUpdates, mutate Cloudflare, touch markers or send messages.
"""
import datetime,json,pathlib,subprocess,sys
R=pathlib.Path("/volume1/docker")
S=R/"RG_TELEGRAM_STATE"
paths={
"cf_freeze":R/"RG_SECRETS/rg_cf_moderation_handoff_freeze",
"cf_deployed_receipt":S/"rg_cf_moderation_handoff_v1/deployed.json",
"cf_scanner_guard_receipt":S/"rg_cf_moderation_handoff_v1/scanner_guard_deployed.json",
"nas_cutover":R/"RG_SECRETS/rg_nas_telegram_cutover_enabled",
"news2_owner":R/"RG_TELEGRAM_NEWS_2/NAS_EXCLUSIVE_OWNER_VERIFIED",
"news2_delivery":R/"RG_TELEGRAM_NEWS_2/MODERATION_DELIVERY_ENABLED",
"news2_publish":R/"RG_TELEGRAM_NEWS_2/PUBLISH_ENABLED",
}
def main():
 report={"schema":"RG_NEWS2_HANDOFF_BATCH_V1","checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
         "read_only":True,"files":{k:p.is_file() and not p.is_symlink() for k,p in paths.items()},
         "activation_checks":{},"allowed_to_enable_news2":False,
         "telegram_polls":0,"telegram_sends":0,"writes":0}
 activator=S/"rg_telegram_nas_selective_moderation_activate_v1.py"
 if activator.is_file() and not activator.is_symlink():
  for mode in ("status","preflight"):
   try:
    proc=subprocess.run([sys.executable,str(activator),mode],capture_output=True,text=True,timeout=80)
    # Only expose sanitized known status and reason fields, never raw output or tokens.
    try: obj=json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError): obj={}
    report["activation_checks"][mode]={"exit_code":proc.returncode,
      "status":str(obj.get("status","UNKNOWN"))[:100],
      "reason":str(obj.get("reason",""))[:100]}
   except (OSError,subprocess.TimeoutExpired) as e:
    report["activation_checks"][mode]={"error_type":type(e).__name__}
 else:report["activation_checks"]["status"]={"status":"ACTIVATOR_MISSING"}
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
