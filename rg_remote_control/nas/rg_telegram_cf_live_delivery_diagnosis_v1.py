#!/usr/bin/env python3
"""One-shot READ-ONLY Cloudflare Telegram news delivery diagnosis.
No Telegram getUpdates, no writes to Workers/KV/DO, no redeploy, no polls,
no source edits and no token printing. Python 3.8 compatible.
External KV health can lag DO-local truth: explicitly mark KV as telemetry.
"""
import argparse,datetime,importlib.util,json,os,pathlib,re,subprocess,sys,time,urllib.parse,urllib.request,urllib.error
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
ACCOUNT="be73f73dbe2a5471c62384dc673c91e6"
KV="d7852688b21b4185b8748b1aa940d978"
SCANNER="rasha-goodbye-video-scanner"
ALERTS="rasha-goodbye-air-alerts"
CONTENT="rasha-goodbye-content-hub"
KEYS={
 "scanner":"telegram-video-scanner-health-v3",
 "moderation":"telegram-video-moderation-health-v2",
 "publication":"telegram-moderation-publish-health-v2",
 "system":"telegram-system-health-v1",
 "starvation":"telegram-starvation-state-v4",
 "dedupe":"telegram-dedupe-protection-v4",
 "automatic_ai_cooldown":"telegram-ai-rate-limit-cooldown-v1",
 "moderator":"telegram-video-moderator-v2",
 "moderation_queue":"telegram-video-moderation-queue-v1",
}
def emit(status,**kw):
 print(json.dumps({"status":status,"read_only":True,
  "telegram_poll_calls":0,"telegram_send_calls":0,
  "cloudflare_writes":0,"nas_runtime_changes":0,**kw},ensure_ascii=False),flush=True)
def mod(name):
 path=STATE/name
 if path.is_symlink() or not path.is_file():raise RuntimeError("NAS_CF_HELPER_MISSING")
 spec=importlib.util.spec_from_file_location("rg_live_health_"+name.replace(".","_"),str(path))
 obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
 return obj
def curl_read(token,route):
 # Secrets only in stdin; never supplied in command-line arguments.
 url="https://api.cloudflare.com/client/v4/"+route
 p=subprocess.run(["curl","-q","-4","-sS","-L","--connect-timeout","8",
  "--max-time","22","--config","-","--write-out","\nRG_HTTP:%{http_code}",
  url],input='header = "Authorization: Bearer '+token+'"\nheader = "Accept: application/json"\n',
  text=True,capture_output=True,timeout=27)
 if p.returncode:raise RuntimeError("CF_GET_TRANSPORT_"+str(p.returncode))
 text=p.stdout
 if "\nRG_HTTP:" not in text:raise RuntimeError("CF_GET_HTTP_STATUS_MISSING")
 raw,code=text.rsplit("\nRG_HTTP:",1)
 try:http=int(code.strip())
 except ValueError:raise RuntimeError("CF_GET_HTTP_STATUS_INVALID")
 return http,raw[:150000]
def scrub_time(value):
 if not isinstance(value,str) or len(value)>40:return None
 try:
  dt=datetime.datetime.fromisoformat(value.replace("Z","+00:00"))
  if dt.tzinfo is None:dt=dt.replace(tzinfo=datetime.timezone.utc)
  seconds=int((datetime.datetime.now(datetime.timezone.utc)-dt).total_seconds())
  return {"at_utc":dt.astimezone(datetime.timezone.utc).isoformat(),
   "age_sec":max(0,seconds),"fresh_under_20min":-120<seconds<1200}
 except ValueError:return None
def number(v):
 if isinstance(v,bool) or not isinstance(v,(int,float)):return None
 return v
def health_projection(name,doc,http):
 if http!=200 or not isinstance(doc,dict):
  return {"http":http,"available":False,"note":"DO-local telemetry can remain live even when shared KV is stale"}
 checked=doc.get("checkedAt") or doc.get("liveCheckedAt") or doc.get("updatedAt")
 p={"http":200,"available":True,"checked":scrub_time(checked),
  "ok":doc.get("ok") if isinstance(doc.get("ok"),bool) else None}
 if name=="scanner":
  for k in ("candidatesQueued","processingQueueRemaining","sourcesAttempted","candidatesSent"):
   p[k]=number(doc.get(k))
  batch=doc.get("batch")
  if isinstance(batch,dict):
   p["batch_sent"]=number(batch.get("candidatesSent"))
   p["batch_failures"]=len(batch["failures"]) if isinstance(batch.get("failures"),list) else None
  text=doc.get("textPosts")
  if isinstance(text,dict):
   p["text_sent"]=number((text.get("batch") or {}).get("sent")) if isinstance(text.get("batch"),dict) else None
 elif name=="moderation":
  for k in ("updatesFetched","updatesProcessed","updatesFailed","offsetBlocked","moderatorConfigured","degraded"):
   v=doc.get(k)
   p[k]=v if isinstance(v,(bool,int)) else None
  # Never echo raw Telegram errors; bucket recognizable error families.
  err=str(doc.get("error") or doc.get("firstFailedError") or "").lower()
  p["error_class"]=("TELEGRAM_CONFLICT_409" if "409" in err else
   "TELEGRAM_TOO_MANY_429" if "429" in err else
   "TELEGRAM_UNAUTHORIZED_401" if "401" in err else
   "CLOUDFLARE_QUOTA" if "quota" in err or "10011" in err else
   "FETCH_FAILED" if err else None)
 elif name=="publication":
  for k in ("published","failed","uncertain","retry","queued"):
   p[k]=number(doc.get(k))
 elif name=="system":
  p["scanner_checked"]=scrub_time((doc.get("scanner") or {}).get("checkedAt")) if isinstance(doc.get("scanner"),dict) else None
  queues=doc.get("moderationQueues")
  p["queues_present"]=isinstance(queues,dict)
  p["automatic_ai_cooldown_present"]=bool((doc.get("ai") or {}).get("automaticCooldownUntil")) if isinstance(doc.get("ai"),dict) else None
 elif name in ("automatic_ai_cooldown","starvation","dedupe"):
  for k in ("active","until","reason"):
   if k=="reason":continue
   val=doc.get(k)
   p[k]=val if isinstance(val,bool) else scrub_time(val)
 elif name=="moderator":
  p["configured"]=bool(doc.get("chatId"))
 elif name=="moderation_queue":
  p["item_count"]=len(doc.get("keys")) if isinstance(doc.get("keys"),list) else None
 return p
def settings(token,name):
 try:
  http,raw=curl_read(token,"accounts/"+ACCOUNT+"/workers/scripts/"+name+"/settings")
  if http!=200:return {"http":http,"owner":"UNREADABLE"}
  result=json.loads(raw).get("result")
  if not isinstance(result,dict):return {"http":http,"owner":"UNREADABLE"}
  bindings=result.get("bindings")
  if not isinstance(bindings,list):return {"http":http,"owner":"UNREADABLE"}
  var="RG_MODERATION_RUNTIME_OWNER" if name==ALERTS else "RG_MIGRATION_SCANNER_OWNER"
  matches=[x.get("text") for x in bindings if isinstance(x,dict) and x.get("name")==var]
  return {"http":200,"owner":matches[0] if matches and matches[0] in ("nas","cloudflare") else "UNDECLARED",
          "telegram_secret_binding_present":any(x.get("name")=="TELEGRAM_BOT_TOKEN" for x in bindings if isinstance(x,dict))}
 except Exception as ex:
  return {"reason":type(ex).__name__,"owner":"UNREADABLE"}
def analytics(token):
 # GraphQL is read-only even though transport uses POST. Missing permissions
 # or unavailable adaptive dataset are reported, not treated as no invocations.
 now=datetime.datetime.now(datetime.timezone.utc)
 lower=now-datetime.timedelta(minutes=75)
 stamp=lambda d:d.strftime("%Y-%m-%dT%H:%M:%SZ")
 query='''query { viewer { accounts(filter: { accountTag: "'''+ACCOUNT+'''" }) { workersInvocationsAdaptive(filter: { datetime_geq: "'''+stamp(lower)+'''", datetime_leq: "'''+stamp(now)+'''" }, limit: 1000) { dimensions { scriptName datetime status } sum { requests errors } } } } }'''
 payload=json.dumps({"query":query}).encode("utf-8")
 url="https://api.cloudflare.com/client/v4/graphql"
 req=urllib.request.Request(url,data=payload,
  headers={"Authorization":"Bearer "+token,"Content-Type":"application/json",
           "User-Agent":"RG-CF-Telegram-Live-ReadOnly"},method="POST")
 try:
  with urllib.request.urlopen(req,timeout=23) as response:
   data=json.loads(response.read(350000))
 except urllib.error.HTTPError as e:return {"status":"UNAVAILABLE","http":e.code}
 except Exception as ex:return {"status":"UNAVAILABLE","reason":type(ex).__name__}
 if data.get("errors"):return {"status":"UNAVAILABLE","reason":"GRAPHQL_QUERY_REJECTED","error_count":len(data["errors"])}
 try:
  accounts=data["data"]["viewer"]["accounts"]
  rows=[r for a in accounts for r in (a.get("workersInvocationsAdaptive") or [])]
 except (KeyError,TypeError,AttributeError):return {"status":"UNAVAILABLE","reason":"GRAPHQL_SHAPE"}
 counts={key:{"requests":0,"errors":0,"latest":None} for key in (SCANNER,ALERTS,CONTENT)}
 for row in rows:
  dim=row.get("dimensions") or {}
  name=dim.get("scriptName")
  if name not in counts:continue
  count=counts[name];summary=row.get("sum") or {}
  count["requests"]+=int(summary.get("requests") or 0)
  count["errors"]+=int(summary.get("errors") or 0)
  timekey=dim.get("datetime")
  if isinstance(timekey,str) and (count["latest"] is None or timekey>count["latest"]):
   count["latest"]=timekey
 return {"status":"AVAILABLE","window_minutes":75,"workers":counts}
def main():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 cf=mod("rg_telegram_cf_cron_pause_v1.py")
 scanner=mod("rg_telegram_cf_selective_scanner_stop_v1.py")
 token=cf.env_token()
 crons=cf.report_live(token)
 own=scanner.get_scanner_owner(token)
 health={}
 for name,key in KEYS.items():
  try:
   http,raw=curl_read(token,"accounts/"+ACCOUNT+
    "/storage/kv/namespaces/"+KV+"/values/"+urllib.parse.quote(key,safe=""))
   if http==200:
    try:doc=json.loads(raw)
    except ValueError:doc=None
   else:doc=None
   health[name]=health_projection(name,doc,http)
  except Exception as ex:health[name]={"available":False,"reason":type(ex).__name__}
 worker_settings={name:settings(token,name) for name in (SCANNER,ALERTS)}
 activity=analytics(token)
 emit("CF_TELEGRAM_LIVE_DELIVERY_DIAGNOSIS",at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  crons=crons,scanner_owner=own,
  worker_settings=worker_settings,
  kv_telemetry=health,
  invocations_75min=activity,
  nas_gate_open=(ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled").is_file(),
  cf_migration_freeze=(ROOT/"RG_SECRETS/rg_cf_moderation_handoff_freeze").is_file(),
  caveat="Shared KV can be stale while scanner/moderation DO-local state is live; GraphQL may be permission-limited")
def selftest():
 d={"checkedAt":"2026-10-12T15:00:00Z","ok":False,"updatesFetched":0,"error":"Telegram getUpdates HTTP 409 with secret xyz"}
 p=health_projection("moderation",d,200)
 assert p["error_class"]=="TELEGRAM_CONFLICT_409"
 assert "secret" not in json.dumps(p)
 assert health_projection("moderation",None,403)["available"] is False
 assert number(True) is None
 emit("CF_TELEGRAM_LIVE_DIAG_SELFTEST_PASS",network_calls=0)
if __name__=="__main__":
 try:
  a=argparse.ArgumentParser();a.add_argument("mode",choices=("selftest","diagnose"))
  x=a.parse_args()
  if x.mode=="selftest":selftest()
  else:main()
 except Exception as ex:
  reason=str(ex)
  if not re.fullmatch(r"[A-Z0-9_]{3,100}",reason):reason=type(ex).__name__
  emit("BLOCKED",reason=reason)
  sys.exit(1)
