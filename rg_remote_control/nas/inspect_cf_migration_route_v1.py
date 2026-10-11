#!/usr/bin/env python3
"""Read-only Cloudflare worker route and RUN_KEY metadata audit. Never prints secrets."""
import json,pathlib,re,urllib.request,urllib.error,sys
ROOT=pathlib.Path("/volume1/docker")
ENV=ROOT/"RG_ALERTS_DEPLOY/deploy.env"
ACCOUNT="be73f73dbe2a5471c62384dc673c91e6"
SCRIPT="rasha-goodbye-air-alerts"
def main():
 if not ENV.is_file():raise ValueError("deploy_env_missing")
 vals={}
 for line in ENV.read_text("utf-8",errors="replace").splitlines():
  m=re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)\s*$",line)
  if m:vals[m.group(1)]=m.group(2).strip().strip("'\"")
 token=vals.get("CLOUDFLARE_API_TOKEN") or vals.get("CF_API_TOKEN")
 if not token:raise ValueError("api_token_unavailable")
 def cf(path):
  req=urllib.request.Request("https://api.cloudflare.com/client/v4/"+path,headers={"Authorization":"Bearer "+token,"Accept":"application/json","User-Agent":"RG-NAS-Route-Audit"})
  try:
   with urllib.request.urlopen(req,timeout=10) as res:return res.status,json.loads(res.read(250000))
  except urllib.error.HTTPError as exc:return exc.code,{}
 out={"mode":"READ_ONLY","worker":SCRIPT,"cloudflare_api_token_found":True,"run_key_in_deploy_env":"RUN_KEY" in vals}
 http,body=cf("accounts/"+ACCOUNT+"/workers/scripts/"+SCRIPT+"/secrets")
 out["worker_secret_list_http"]=http
 out["run_key_secret_exists"]=any(x.get("name")=="RUN_KEY" for x in body.get("result",[]) if isinstance(x,dict)) if http==200 else None
 http,body=cf("accounts/"+ACCOUNT+"/workers/domains")
 domains=body.get("result",[]) if isinstance(body.get("result"),list) else []
 matches=[{"hostname":str(x.get("hostname") or ""), "zone_id_present":bool(x.get("zone_id"))} for x in domains if x.get("service")==SCRIPT or x.get("script")==SCRIPT]
 out["domain_list_http"]=http
 out["worker_custom_domains"]=matches[:10]
 http,body=cf("accounts/"+ACCOUNT+"/workers/subdomain")
 sub=body.get("result") or {}
 out["workers_subdomain_http"]=http
 out["workers_subdomain_present"]=bool(sub.get("subdomain"))
 out["note"]="No key, authorization header, or full URL printed; no deploy; no Telegram calls"
 print(json.dumps(out,ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","reason":type(e).__name__+"_"+str(e)[:60]}))
  sys.exit(1)
