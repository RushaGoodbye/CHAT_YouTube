#!/usr/bin/env python3
"""Read-only AI provider route discovery for NEWS RG (Python 3.8+).

Cloudflare: check existing content-hub worker secret *names*, not values,
using existing NAS Cloudflare deployment token. No deploy or token output.
Ollama: probe loopback and already-named AlexPC on default port for model
listing only; no model requests, no network scan.
"""
import json
import os
import pathlib
import re
import socket
import sys
import tempfile
import urllib.error
import urllib.request

ROOT=pathlib.Path("/volume1/docker")
CF_CONFIG=(ROOT/"RG_CONTENT_DEPLOY/deploy.env",
           ROOT/"RG_ALERTS_DEPLOY/deploy.env",
           ROOT/"RG_DEPLOY/deploy.env")
CF_API="https://api.cloudflare.com/client/v4/accounts/"
CF_ACCOUNT="be73f73dbe2a5471c62384dc673c91e6"
CF_WORKER="rasha-goodbye-content-hub"
ALLOWED_CF_TOKEN_KEYS=("CLOUDFLARE_API_TOKEN","CF_API_TOKEN","CLOUDFLARE_TOKEN")

def existing_cf_token(root=ROOT):
    for where in CF_CONFIG:
        path=root/where.relative_to(ROOT)
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size>65536:continue
            rows=path.read_text(encoding="utf-8").splitlines()
        except (OSError,UnicodeError):continue
        data={}
        for line in rows:
            m=re.fullmatch(r'\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*',line)
            if not m:continue
            k,v=m.groups()
            if k in ALLOWED_CF_TOKEN_KEYS:
                value=v.strip().strip('"').strip("'")
                if value and not any(c in value for c in " \n\r\t$"):
                    data[k]=value
        for key in ALLOWED_CF_TOKEN_KEYS:
            if key in data:return data[key]
    return None

def cf_secret_names(token, urlopen=urllib.request.urlopen):
    if not token:return {"status":"NO_LOCAL_CF_CONTROL_TOKEN",
                        "gemini_worker_secret_present":False,
                        "can_reuse_worker_ai_from_nas":False}
    url=(CF_API+CF_ACCOUNT+"/workers/scripts/"+CF_WORKER+"/secrets")
    req=urllib.request.Request(url,headers={
       "Authorization":"Bearer "+token,
       "User-Agent":"NEWS-RG-Provider-Audit/1.0",
       "Accept":"application/json"},method="GET")
    try:
        with urlopen(req,timeout=10) as res:
            if res.status!=200:
                return {"status":"CF_SECRETS_HTTP_"+str(res.status)}
            data=json.loads(res.read(100000))
    except urllib.error.HTTPError as e:
        return {"status":"CF_SECRETS_HTTP_"+str(e.code)}
    except (urllib.error.URLError,TimeoutError,OSError,ValueError,KeyError):
        return {"status":"CF_SECRETS_READ_UNAVAILABLE"}
    if not isinstance(data,dict) or data.get("success") is not True \
       or not isinstance(data.get("result"),list):
        return {"status":"CF_RESPONSE_UNEXPECTED"}
    names={x.get("name") for x in data["result"] if isinstance(x,dict)}
    return {"status":"CF_SECRETS_METADATA_OK",
       "gemini_worker_secret_present":"GEMINI_API_KEY" in names,
       "telegram_bot_worker_secret_present":"TELEGRAM_BOT_TOKEN" in names,
       "can_reuse_worker_ai_from_nas":False,
       "reason":"Existing worker does not expose authorized NEWS RG rewrite route"}

def ollama_status(host,opener=urllib.request.urlopen):
    try:
        req=urllib.request.Request(
            "http://"+host+":11434/api/tags",
            headers={"User-Agent":"NEWS-RG-Local-Probe/1.0"})
        with opener(req,timeout=3) as r:
            if r.status!=200:return {"status":"UNAVAILABLE"}
            data=json.loads(r.read(32000))
            names=[x.get("name","") for x in data.get("models",[])
                   if isinstance(x,dict)]
            valid=[x for x in names if isinstance(x,str) and
                   re.fullmatch(r"[A-Za-z0-9_.:/-]{2,100}",x)]
            return {"status":"AVAILABLE" if valid else "NO_MODELS",
                "ukrainian_capable_local_model_candidate":any(
                 any(word in x.lower() for word in
                     ("qwen","llama","gemma","mistral","phi"))
                 for x in valid),
                "model_names":valid[:8]}
    except (urllib.error.URLError,TimeoutError,OSError,ValueError,
            KeyError,TypeError):
        return {"status":"UNREACHABLE"}

def audit(root=ROOT,cf_check=cf_secret_names,ollama=ollama_status):
    secret=existing_cf_token(root)
    cf=cf_check(secret)
    routes={"nas_ollama":ollama("127.0.0.1"),
            "alexpc_ollama":ollama("ALEXPC")}
    return {"schema":"NEWS_RG_EXISTING_AI_ROUTES_AUDIT_V1",
      "read_only":True,"cloudflare_metadata":cf,
      "local_ollama_routes":routes,
      "worker_ai_publication_route_enabled":False,
      "nas_cloudflare_secret_value_exposed":False,
      "gemini_secret_value_exposed":False,
      "ai_generation_requests":0,"telegram_api_calls":0,
      "second_telegram_poller_started":False,
      "publications":0,"db_writes":0}

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        p=root/"RG_CONTENT_DEPLOY";p.mkdir()
        (p/"deploy.env").write_text("CLOUDFLARE_API_TOKEN=TEST_SECRET_TOKEN_123\n")
        assert existing_cf_token(root)=="TEST_SECRET_TOKEN_123"
        fakecf=lambda token:{
            "status":"CF_SECRETS_METADATA_OK",
            "gemini_worker_secret_present":True,
            "can_reuse_worker_ai_from_nas":False}
        fakeollama=lambda host:{"status":"AVAILABLE" if host=="ALEXPC"
                                                else "UNREACHABLE"}
        result=audit(root,fakecf,fakeollama)
        assert result["cloudflare_metadata"]["gemini_worker_secret_present"]
        assert result["local_ollama_routes"]["alexpc_ollama"]["status"]=="AVAILABLE"
        assert "TEST_SECRET_TOKEN_123" not in json.dumps(result)
        assert result["ai_generation_requests"]==0
    print("NEWS_RG_EXISTING_AI_ROUTES_AUDIT_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(audit(),sort_keys=True,ensure_ascii=False,indent=2))
    else:raise SystemExit("Only selftest and inspect supported")
