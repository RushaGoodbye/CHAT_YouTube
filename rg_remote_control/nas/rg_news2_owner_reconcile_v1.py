#!/usr/bin/env python3
"""Read-only News2 ownership handoff evidence report. No marker creation or API polling."""
import datetime,importlib.util,json,os,pathlib,sys
R=pathlib.Path("/volume1/docker");T=R/"RG_TELEGRAM_STATE";S=R/"RG_SECRETS"
def load(p):
 spec=importlib.util.spec_from_file_location("cf_owner_audit",str(p));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def flag(p):return p.is_file() and not p.is_symlink()
def main():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 m=load(T/"rg_telegram_cf_selective_moderation_handoff_v1.py")
 token=m.module().env_token()
 live={n:m.cron(token,n) for n in (m.WORKER,)+m.OTHER}
 owner=m.owner(token)
 guard=load(T/"rg_telegram_cf_selective_scanner_stop_v1.py")
 scanner_owner=guard.get_scanner_owner(token)
 receipt=T/"rg_cf_moderation_handoff_v1/deployed.json"
 gates={"native":flag(S/"rg_nas_telegram_cutover_enabled"),
        "news2_owner":flag(R/"RG_TELEGRAM_NEWS_2/NAS_EXCLUSIVE_OWNER_VERIFIED"),
        "news2_delivery":flag(R/"RG_TELEGRAM_NEWS_2/MODERATION_DELIVERY_ENABLED")}
 state={"schema":"RG_NEWS2_OWNER_RECONCILE_V1",
 "at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "cloudflare_moderation_owner":owner,"cloudflare_scanner_do_owner":scanner_owner,
 "crons":live,"handoff_receipt":flag(receipt),"gates":gates,
 "cloudflare_remote_code_guard_previously_observed":True,
 "sole_getupdates_poll_owner_verified":False,"activation_allowed":False,
 "missing_proofs":["live Worker code semantics are not proven by string checks",
                   "unobserved DO alarm/other hosts could still poll",
                   "canonical handoff deployed receipt absent" if not flag(receipt) else "independent owner confirmation required"],
 "telegram_sends":0,"telegram_polls":0,"cloudflare_writes":0,"local_writes":0}
 print(json.dumps(state,ensure_ascii=False,indent=2))
if __name__=="__main__":
 try:main()
 except Exception as ex:
  print(json.dumps({"status":"BLOCKED","reason_type":type(ex).__name__}));sys.exit(1)
