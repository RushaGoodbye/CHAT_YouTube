#!/usr/bin/env python3
"""Read-only NAS Cloudflare feed configuration discovery. Never prints secrets or URLs."""
import json,pathlib,re,urllib.parse,os
root=pathlib.Path("/volume1/docker")
secrets=root/"RG_SECRETS"
paths=[root/"RG_ALERTS_DEPLOY/deploy.env",root/"RG_ALERTS_DEPLOY/cloudflare-alerts/.env",root/"RG_ALERTS_DEPLOY/cloudflare-alerts/.dev.vars",root/"RG_NAS_STATE/alerts_worker_url",root/"RG_NAS_CONTROL/admin_url"]
names=set()
for path in paths:
 if not path.is_file():continue
 try:
  for line in path.read_text("utf-8",errors="replace").splitlines():
   match=re.match(r'^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=',line)
   if match:names.add(match.group(1))
 except OSError:pass
candidate_names=["RUN_KEY","ALERTS_RUN_KEY","CLOUDFLARE_RUN_KEY","RG_RUN_KEY","TELEGRAM_RUN_KEY","WORKER_URL","ALERTS_WORKER_URL","CF_WORKER_URL","CF_API_TOKEN","CLOUDFLARE_API_TOKEN"]
out={"status":"READ_ONLY","nas_bridge_installed":(root/"RG_TELEGRAM_STATE/rg_telegram_cf_decision_import_v1.py").is_file(),"configured_endpoint":(secrets/"rg_cf_migration_endpoint").is_file(),"configured_run_key":(secrets/"rg_cf_migration_run_key").is_file(),"existing_named_secret_files":{k:any((secrets/k).is_file() for k in (name,name.lower())) for k,name in [(x,x) for x in candidate_names]},"configured_variable_names":[x for x in candidate_names if x in names],"cloudflare_deploy_env_present":paths[0].is_file(),"telegram_sends":False}
print(json.dumps(out))
