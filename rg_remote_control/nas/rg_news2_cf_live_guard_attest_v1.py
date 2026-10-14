#!/usr/bin/env python3
"""Read-only remote Cloudflare Worker moderation guard attestation; never print credentials/source."""
import importlib.util,json,pathlib,sys,urllib.request,urllib.error
R=pathlib.Path("/volume1/docker")
P=R/"RG_TELEGRAM_STATE/rg_telegram_cf_selective_moderation_handoff_v1.py"
def main():
 spec=importlib.util.spec_from_file_location("rg_cf_audit",str(P));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 token=m.module().env_token()
 owner=m.owner(token)
 crons={k:m.cron(token,k) for k in (m.WORKER,)+m.OTHER}
 url=f"https://api.cloudflare.com/client/v4/accounts/{m.CF_ACCOUNT}/workers/scripts/{m.WORKER}"
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"User-Agent":"RG-Live-Guard-Readback/1"},method="GET")
 try:
  with urllib.request.urlopen(req,timeout=20) as r:
   data=r.read(4_000_001)
   ct=r.headers.get("Content-Type","")
  if len(data)>4_000_000:raise RuntimeError("REMOTE_SCRIPT_TOO_LARGE")
  content=data.decode("utf-8","replace")
  # In bundled/transformed Worker source, these checks are corroborative, not complete proof.
  checks={"owner_variable": "RG_MODERATION_RUNTIME_OWNER" in content,
          "nas_skip": "nas_moderation_owner" in content,
          "legacy_poll_call": "processTelegramModerationUpdates" in content}
  remote_status="GUARD_STRINGS_PRESENT" if all(checks.values()) else "GUARD_UNVERIFIED"
 except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError) as ex:
  remote_status="REMOTE_READ_FAILED_"+type(ex).__name__;checks={}
 print(json.dumps({"status":"RG_CF_LIVE_GUARD_AUDIT","owner_binding":owner,"cron_schedules":crons,
 "remote_script_status":remote_status,"remote_checks":checks,
 "exclusive_getupdates_owner_proven":False,"deployed_receipt_created":False,
 "telegram_sends":0,"telegram_polls":0,"writes":0},ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as ex:
  print(json.dumps({"status":"BLOCKED","error_type":type(ex).__name__}));sys.exit(1)
