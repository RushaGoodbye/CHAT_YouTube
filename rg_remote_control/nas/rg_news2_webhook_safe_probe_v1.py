#!/usr/bin/env python3
"""News2 owner readiness: getWebhookInfo is read-only, does not consume updates."""
import json,os,pathlib,sys
BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
sys.path.insert(0,str(BASE))
import rg_moderation as m
def main():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 state=m.status()
 remote=m.api("getWebhookInfo",{})
 output={
  "status":"OWNER_INPUTS_CHECKED",
  "webhook_active":bool(remote.get("url")),
  "pending_update_count":remote.get("pending_update_count"),
  "last_error_present":bool(remote.get("last_error_message")),
  "allowed_updates":remote.get("allowed_updates"),
  "local_owner_gate":(BASE/"NAS_EXCLUSIVE_OWNER_VERIFIED").is_file(),
  "delivery_gate":state.get("gate_enabled"),
  "dispatch":state.get("dispatch"),
  "channel_publish_gate":(BASE/"PUBLISH_ENABLED").exists(),
  "telegram_poll_calls":0,
  "channel_sends":0,
  "owner_exclusive_proven":False
 }
 print(json.dumps(output,ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","error_type":type(e).__name__}))
  sys.exit(1)
