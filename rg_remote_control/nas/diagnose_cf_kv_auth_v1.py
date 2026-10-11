#!/usr/bin/env python3
"""Cloudflare auth diagnosis, no token output and no writes."""
import json,pathlib,re,urllib.request,urllib.error
p=pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/deploy.env")
vals={}
for line in p.read_text(errors="replace").splitlines():
 m=re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$",line)
 if m:vals[m.group(1)]=m.group(2).strip().strip("'\"")
token=vals.get("CLOUDFLARE_API_TOKEN","")
account="be73f73dbe2a5471c62384dc673c91e6"
namespace="d7852688b21b4185b8748b1aa940d978"
checks={"token_verify":"user/tokens/verify","kv_namespace":"accounts/"+account+"/storage/kv/namespaces/"+namespace,"kv_keys":"accounts/"+account+"/storage/kv/namespaces/"+namespace+"/keys?limit=1","worker_secrets":"accounts/"+account+"/workers/scripts/rasha-goodbye-air-alerts/secrets"}
out={"mode":"READ_ONLY","token_configured":bool(token),"results":{}}
for name,part in checks.items():
 req=urllib.request.Request("https://api.cloudflare.com/client/v4/"+part,headers={"Authorization":"Bearer "+token,"Accept":"application/json","User-Agent":"RG-NAS-CF-Auth-Audit"})
 try:
  with urllib.request.urlopen(req,timeout=12) as res:
   out["results"][name]={"http":res.status}
 except urllib.error.HTTPError as e:
  out["results"][name]={"http":e.code}
 except Exception as e:
  out["results"][name]={"error":type(e).__name__}
print(json.dumps(out))
