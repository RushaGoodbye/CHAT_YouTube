#!/usr/bin/env python3
"""RG Telegram NAS migration: controlled reversible Cloudflare Cron pause.
Authorised by operator. Never opens Telegram Bot getUpdates or sends messages.
Does NOT claim scanner Durable Object alarms have stopped.
Commands: selftest, status, pause, restore.
"""
import argparse,datetime,json,os,pathlib,re,shutil,subprocess,sys,tempfile,time,urllib.error,urllib.request
ROOT=pathlib.Path("/volume1/docker")
SECRETS=ROOT/"RG_SECRETS"
STATE=ROOT/"RG_TELEGRAM_STATE"
SESSION=STATE/"rg_cf_cron_pause_v1"
MARKER=SECRETS/"rg_cloudflare_migration_pause"
DEPLOY=ROOT/"RG_NAS_AUTO_DEPLOY.sh"
LOCK=ROOT/"RG_NAS_STATE/deploy.lock"
ACCOUNT="be73f73dbe2a5471c62384dc673c91e6"
NAMES=("rasha-goodbye-video-scanner","rasha-goodbye-air-alerts","rasha-goodbye-content-hub")
ENVS=(ROOT/"RG_ALERTS_DEPLOY/deploy.env",ROOT/"RG_CONTENT_DEPLOY/deploy.env",ROOT/"RG_DEPLOY/deploy.env")
GUARD="# RG_NAS_CLOUDFLARE_MIGRATION_PAUSE_V1"
BLOCK='''# RG_NAS_CLOUDFLARE_MIGRATION_PAUSE_V1
# Suppress Cloudflare source redeploy while NAS owns the cutover.
if [ -f "$ROOT/RG_SECRETS/rg_cloudflare_migration_pause" ]; then
  note_owner_state PAUSED_MIGRATION
  printf '%s\n' "RG_NAS_CLOUDFLARE_DEPLOY_PAUSED_MIGRATION"
  exit 0
fi

'''
ANCHOR="acquire_deploy_lock\nnote_owner_state RUNNING"
def emit(status,**kw):
 print(json.dumps({"status":status,"telegram_polls":0,"telegram_sends":0,
 "nas_bot_gate_opened":False,"cf_do_alarm_paused_verified":False,**kw},ensure_ascii=False),flush=True)
def env_token():
 for file in ENVS:
  if file.is_symlink() or not file.is_file():continue
  try:
   if file.stat().st_size>100000:continue
   value=file.read_text("utf-8")
  except (OSError,UnicodeError):continue
  names={}
  for row in value.splitlines():
   m=re.fullmatch(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)\s*",row)
   if m:
    k,v=m.groups();names[k]=v.strip().strip("'\"")
  for name in ("CLOUDFLARE_API_TOKEN","CF_API_TOKEN","CLOUDFLARE_TOKEN"):
   token=names.get(name,"")
   if token and "$" not in token and len(token)>=25:return token
 raise RuntimeError("CF_API_TOKEN_UNAVAILABLE")
def cf_get_ipv4_curl(token,endpoint,name):
 """GET-only alternative transport; auth header is supplied on stdin, not argv."""
 curl=shutil.which("curl")
 if not curl:raise RuntimeError(f"CF_GET_{name}_CURL_MISSING")
 if not re.fullmatch(r"[A-Za-z0-9_-]{25,500}",token):
  raise RuntimeError("CF_TOKEN_FORMAT_INVALID")
 cfg='header = "Authorization: Bearer '+token+'"\n'
 try:
  p=subprocess.run([curl,"-q","-4","-sS","-f","--connect-timeout","7","--max-time","16",
    "--config","-",endpoint],input=cfg,text=True,capture_output=True,timeout=20)
 except (OSError,subprocess.TimeoutExpired):
  raise RuntimeError(f"CF_GET_{name}_CURL_TIMEOUT") from None
 if p.returncode:
  codes={6:"DNS",7:"CONNECT",22:"HTTP",28:"TIMEOUT",35:"TLS",51:"TLS",52:"EMPTY",56:"CONNECTION_RESET",60:"CA_CERT"}
  raise RuntimeError(f"CF_GET_{name}_CURL_{codes.get(p.returncode,'ERROR')}") from None
 if len(p.stdout)>65536:raise RuntimeError("CF_RESPONSE_TOO_LARGE")
 try:return json.loads(p.stdout)
 except ValueError:raise RuntimeError("CF_RESPONSE_JSON_INVALID") from None
def cf_put_ipv4_curl(token,endpoint,name,body):
 """One-attempt PUT via curl IPv4; bearer and JSON body supplied over stdin.
 Never replay a PUT when transport status is uncertain; readback + rollback.
 """
 curl=shutil.which("curl")
 if not curl:raise RuntimeError(f"CF_PUT_{name}_CURL_MISSING")
 if not re.fullmatch(r"[A-Za-z0-9_-]{25,500}",token):
  raise RuntimeError("CF_TOKEN_FORMAT_INVALID")
 if not isinstance(body,list) or len(body)>5:
  raise RuntimeError("CF_PUT_BODY_INVALID")
 body_data=json.dumps(body,separators=(",",":"))
 if len(body_data)>1200:raise RuntimeError("CF_PUT_BODY_TOO_LARGE")
 config='header = "Authorization: Bearer '+token+'"\n'
 config+='header = "Content-Type: application/json"\n'
 # curl config stdin is an isolated private pipe; no token in argv or files.
 # Use -d with a JSON argument containing only public Cron expressions.
 try:
  p=subprocess.run([curl,"-q","-4","-sS","-f","--connect-timeout","7","--max-time","16",
     "--config","-","-X","PUT","--data-raw",body_data,endpoint],
     input=config,text=True,capture_output=True,timeout=20)
 except (OSError,subprocess.TimeoutExpired):
  raise RuntimeError(f"CF_PUT_{name}_NETWORK_UNCERTAIN") from None
 if p.returncode:
  if p.returncode==22:
   raise RuntimeError(f"CF_PUT_{name}_CURL_HTTP") from None
  raise RuntimeError(f"CF_PUT_{name}_NETWORK_UNCERTAIN") from None
 if len(p.stdout)>65536:raise RuntimeError("CF_RESPONSE_TOO_LARGE")
 try:return json.loads(p.stdout)
 except ValueError:raise RuntimeError("CF_RESPONSE_JSON_INVALID") from None

def cf_call(token,method,name,body=None):
 if name not in NAMES:raise RuntimeError("WORKER_NOT_APPROVED")
 endpoint=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts/{name}/schedules"
 headers={"Authorization":"Bearer "+token,"User-Agent":"RG-NAS-Migration-Pause/2"}
 if body is not None:headers["Content-Type"]="application/json"
 payload=None if body is None else json.dumps(body,separators=(",",":")).encode("utf-8")
 response=None
 if method=="PUT":
  response=cf_put_ipv4_curl(token,endpoint,name,body)
  return cf_schedule_result(response,method,name)
 # Only GETs are retried/fallbacked without side effects. Never replay an
 # uncertain PUT: the caller must read back and reconcile first.
 max_attempts=2 if method=="GET" else 1
 for attempt in range(max_attempts):
  req=urllib.request.Request(endpoint,data=payload,headers=headers,method=method)
  try:
   with urllib.request.urlopen(req,timeout=10) as r:raw=r.read(65537)
   if len(raw)>65536:raise RuntimeError("CF_RESPONSE_TOO_LARGE")
   response=json.loads(raw)
   break
  except urllib.error.HTTPError as e:
   raise RuntimeError(f"CF_{method}_{name}_HTTP_{e.code}") from None
  except ValueError:
   raise RuntimeError("CF_RESPONSE_JSON_INVALID") from None
  except (urllib.error.URLError,OSError,TimeoutError) as ex:
   if method!="GET":
    raise RuntimeError(f"CF_PUT_{name}_NETWORK_UNCERTAIN") from None
   if attempt+1<max_attempts:
    time.sleep(1+attempt)
    continue
   response=cf_get_ipv4_curl(token,endpoint,name)
 return cf_schedule_result(response,method,name)
def cf_schedule_result(response,method,name):
 if not isinstance(response,dict) or response.get("success") is not True:
  raise RuntimeError(f"CF_{method}_{name}_ERROR")
 result=response.get("result")
 schedules=result.get("schedules") if isinstance(result,dict) else None
 if not isinstance(schedules,list):raise RuntimeError("CF_SCHEDULES_MISSING")
 crons=[x.get("cron") for x in schedules if isinstance(x,dict)]
 if len(crons)!=len(schedules) or not all(isinstance(x,str) for x in crons):
  raise RuntimeError("CF_SCHEDULES_INVALID")
 return crons
def patch(text):
 if text.count(GUARD)==1:return text,"ALREADY_GUARDED"
 if text.count(GUARD)>1:raise RuntimeError("DEPLOY_GUARD_DUPLICATED")
 if text.count(ANCHOR)!=1:raise RuntimeError("DEPLOY_ANCHOR_NOT_FOUND")
 return text.replace(ANCHOR,BLOCK+ANCHOR,1),"PATCHED"
def shell_ok(body):
 r=subprocess.run(["/bin/sh","-n"],input=body,text=True,capture_output=True,timeout=6)
 if r.returncode:raise RuntimeError("DEPLOY_SHELL_SYNTAX_ERROR")
def write_secure(path,value):
 if path.is_symlink():raise RuntimeError("SYMLINK_REFUSED")
 fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix=".rg-migrate-")
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as w:w.write(value)
  os.chmod(tmp,0o600);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def check_deploy_idle():
 if not LOCK.exists():return
 if LOCK.is_symlink():raise RuntimeError("DEPLOY_LOCK_SYMLINK")
 pidfile=LOCK/"pid";startfile=LOCK/"started_at"
 try:pid=int(pidfile.read_text().strip())
 except (OSError,ValueError):pid=0
 try:started=int(startfile.read_text().strip())
 except (OSError,ValueError):started=0
 now=int(datetime.datetime.now(datetime.timezone.utc).timestamp())
 if (started and 0<=now-started<2400) or (pid and pathlib.Path(f"/proc/{pid}").exists()):
  raise RuntimeError("ACTIVE_NAS_AUTO_DEPLOY")
def snapshot_path():return SESSION/"original_schedules.json"
def state_from_disk():
 p=snapshot_path()
 if not p.is_file() or p.is_symlink():raise RuntimeError("ORIGINAL_SCHEDULE_BACKUP_MISSING")
 d=json.loads(p.read_text("utf-8"))
 if d.get("account")!=ACCOUNT or set(d.get("schedules",{}))!=set(NAMES):
  raise RuntimeError("ORIGINAL_SCHEDULE_BACKUP_INVALID")
 for k,v in d["schedules"].items():
  if k not in NAMES or not isinstance(v,list) or not all(isinstance(c,str) and len(c)<100 for c in v):
   raise RuntimeError("ORIGINAL_SCHEDULE_BACKUP_INVALID")
 return d
def report_live(token):
 return {name:cf_call(token,"GET",name) for name in NAMES}
def status():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 token=env_token();current=report_live(token)
 emit("CF_CRON_MIGRATION_STATUS",cloudflare_crons=current,
    paused_marker_present=MARKER.exists(),
    all_3_schedules_empty=all(not x for x in current.values()),
    rollback_backup=snapshot_path().is_file(),
    independent_do_alarm_possible=True)
def prepare():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if not DEPLOY.is_file() or DEPLOY.is_symlink():raise RuntimeError("NAS_AUTODEPLOY_MISSING")
 if not (STATE/"rg_telegram_nas_native_bot_v01.py").is_file():raise RuntimeError("NATIVE_BOT_NOT_INSTALLED")
 if not (STATE/"rg_telegram_nas_minute_silence_v1.py").is_file():raise RuntimeError("NAS_MINUTE_NOT_INSTALLED")
 if (SECRETS/"rg_nas_telegram_cutover_enabled").exists():raise RuntimeError("NATIVE_BOT_ALREADY_ACTIVE")
 check_deploy_idle()
 text=DEPLOY.read_text("utf-8");changed,mode=patch(text);shell_ok(changed)
 current=report_live(env_token())
 if not all(current.values()):raise RuntimeError("CRONS_ALREADY_PARTIALLY_PAUSED")
 if SESSION.is_symlink():raise RuntimeError("MIGRATION_STATE_SYMLINK")
 SESSION.mkdir(parents=True,exist_ok=True,mode=0o700)
 os.chmod(SESSION,0o700)
 path=snapshot_path()
 if path.exists():
  old=state_from_disk()
  if old["schedules"]!=current:raise RuntimeError("SCHEDULES_DIFFER_FROM_PREVIOUS_BACKUP")
 else:
  write_secure(path,json.dumps({"account":ACCOUNT,"saved_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
   "schedules":current},indent=2)+"\n")
 if mode=="PATCHED":
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  shutil.copy2(DEPLOY,SESSION/("RG_NAS_AUTO_DEPLOY.sh."+stamp+".bak"))
  fd,tgt=tempfile.mkstemp(prefix=".rg-deploy-guard-",dir=str(DEPLOY.parent))
  try:
   with os.fdopen(fd,"w") as w:w.write(changed)
   shutil.copymode(DEPLOY,tgt)
   os.replace(tgt,DEPLOY)
  finally:
   if os.path.exists(tgt):os.unlink(tgt)
 emit("CF_CRON_PAUSE_PREPARED",original=current,
   autodeploy_guard=mode,rollback_file_saved=True,cf_crons_changed=False)
def pause():
 prepare()
 token=env_token()
 write_secure(MARKER,json.dumps({"reason":"RG Telegram NAS migration",
   "created_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()})+"\n")
 completed=[]
 try:
  for name in NAMES:
   new=cf_call(token,"PUT",name,[])
   if new:raise RuntimeError(f"CF_SCHEDULE_NOT_EMPTY_{name}")
   completed.append(name)
  live=report_live(token)
  if any(live.values()):raise RuntimeError("SCHEDULES_STILL_ACTIVE")
 except Exception:
  # Compare live state BEFORE a rollback. A denied first PUT must never
  # trigger three unnecessary write attempts to already-correct workers.
  original=state_from_disk()["schedules"]
  try:live_after=report_live(token)
  except Exception:
   raise RuntimeError("CRON_PAUSE_FAILED_READBACK_UNAVAILABLE") from None
  changed=[name for name in NAMES if sorted(live_after[name])!=sorted(original[name])]
  if not changed:
   if MARKER.is_file() and not MARKER.is_symlink():MARKER.unlink()
   raise RuntimeError("CRON_PAUSE_FAILED_NO_REMOTE_CHANGE") from None
  errors=[]
  for name in changed:
   try:
    result=cf_call(token,"PUT",name,[{"cron":c} for c in original[name]])
    if sorted(result)!=sorted(original[name]):errors.append(name)
   except Exception:errors.append(name)
  try:live_verified=report_live(token)
  except Exception:live_verified=None
  if live_verified!=original:errors.append("READBACK")
  if not errors:
   if MARKER.is_file() and not MARKER.is_symlink():MARKER.unlink()
  raise RuntimeError("CRON_PAUSE_FAILED_ROLLBACK_"+("SUCCESS" if not errors else "INCOMPLETE")) from None
 write_secure(SESSION/"paused.json",json.dumps({"paused_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "workers":NAMES,"note":"DO independent alarm may still run; no NAS gate enabled"})+"\n")
 emit("CF_THREE_CRONS_PAUSED",cloudflare_crons=live,
   autodeploy_frozen=True,rollback_available=True,native_bot_not_started=True,
   independent_scanner_do_alarm="NOT_DISABLED",
   next_step="stop_DO_alarm_via_guard_deploy_then_verify_before_NAS_gate")
def restore():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 backup=state_from_disk()
 token=env_token()
 expected=backup["schedules"]
 for name in NAMES:
  result=cf_call(token,"PUT",name,[{"cron":cron} for cron in expected[name]])
  if sorted(result)!=sorted(expected[name]):raise RuntimeError("ROLLBACK_CF_VERIFY_FAILED")
 live=report_live(token)
 if live!=expected:raise RuntimeError("ROLLBACK_CF_READBACK_MISMATCH")
 if MARKER.is_file() and not MARKER.is_symlink():MARKER.unlink()
 emit("CF_ALL_CRONS_RESTORED",restored=live,autodeploy_pause_marker_removed=True)
def watchdog():
 # Protect Kyiv alerts and scheduled posts from an indefinite migration outage.
 # If NAS was not activated within 45 minutes, restore original CF crons.
 gate=SECRETS/"rg_nas_telegram_cutover_enabled"
 if gate.exists():
  emit("CF_PAUSE_WATCHDOG_NAS_ACTIVE",recovery="NOT_NEEDED")
  return
 marker=SESSION/"paused.json"
 if not marker.is_file():
  emit("CF_PAUSE_WATCHDOG_IDLE",recovery="NOT_NEEDED")
  return
 try:
  row=json.loads(marker.read_text("utf-8"))
  stamp=datetime.datetime.fromisoformat(row["paused_utc"])
  age=(datetime.datetime.now(datetime.timezone.utc)-stamp).total_seconds()
 except (OSError,ValueError,KeyError):
  raise RuntimeError("WATCHDOG_PAUSE_STATE_INVALID")
 if age<45*60:
  emit("CF_PAUSE_WATCHDOG_WAITING",elapsed_seconds=int(age),recovery_after_seconds=2700)
  return
 if not MARKER.exists():raise RuntimeError("MIGRATION_MARKER_MISSING")
 restore()
 emit("CF_PAUSE_WATCHDOG_ROLLBACK_COMPLETE",recovery="CLOUDFLARE_CRONS_RESTORED")
def selftest():
 sample="#!/bin/sh\nROOT=\"/volume1/docker\"\nnote_owner_state() { :; }\nacquire_deploy_lock\nnote_owner_state RUNNING\n"
 res,mode=patch(sample)
 assert mode=="PATCHED" and GUARD in res
 assert patch(res)==(res,"ALREADY_GUARDED")
 shell_ok(res)
 try:patch("set -eu\n")
 except RuntimeError:pass
 else:raise AssertionError("unrecognized_deployer_accepted")
 assert set(NAMES)=={"rasha-goodbye-air-alerts","rasha-goodbye-content-hub","rasha-goodbye-video-scanner"}
 # Explicit contract tests for the human-readable errors formerly masked by RuntimeError.
 assert re.fullmatch(r"CF_(GET|PUT)_rasha-goodbye-(video-scanner|air-alerts|content-hub)_(HTTP_[0-9]{3}|NETWORK_UNCERTAIN|CURL_[A-Z_]+|ERROR)","CF_GET_rasha-goodbye-air-alerts_CURL_DNS")
 assert json.loads('{"success":true,"result":{"schedules":[{"cron":"* * * * *"}]}}')["result"]["schedules"][0]["cron"]=="* * * * *"
 # Offline: force Python HTTPS transport failure, prove IPv4 fallback is used.
 from unittest import mock
 fake={"success":True,"result":{"schedules":[{"cron":"* * * * *"}]}}
 with mock.patch("urllib.request.urlopen",side_effect=urllib.error.URLError("simulated_dns")) as opening:
  with mock.patch(__name__+".cf_get_ipv4_curl",return_value=fake) as ipv4:
   with mock.patch("time.sleep"):
    assert cf_call("A"*40,"GET","rasha-goodbye-air-alerts")==["* * * * *"]
    assert opening.call_count==2 and ipv4.call_count==1
 # One PUT via IPv4 only, no retries and no leakage to argv.
 with mock.patch(__name__+".cf_put_ipv4_curl",return_value=fake) as write:
  assert cf_call("A"*40,"PUT","rasha-goodbye-air-alerts",[])==["* * * * *"]
  assert write.call_count==1
 # Transport uncertainty propagates and prevents any unsafe replay.
 with mock.patch(__name__+".cf_put_ipv4_curl",side_effect=RuntimeError("CF_PUT_rasha-goodbye-air-alerts_NETWORK_UNCERTAIN")) as write:
  try:cf_call("A"*40,"PUT","rasha-goodbye-air-alerts",[])
  except RuntimeError as ex:
   assert str(ex)=="CF_PUT_rasha-goodbye-air-alerts_NETWORK_UNCERTAIN"
  else:raise AssertionError("unsafe PUT retry")
  assert write.call_count==1

 emit("CF_MIGRATION_PAUSE_SELFTEST_PASS",rollback="IMPLEMENTED",dry_run=True,network_calls=0)
if __name__=="__main__":
 try:
  p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","status","prepare","pause","restore","watchdog"))
  a=p.parse_args()
  {"selftest":selftest,"status":status,"prepare":prepare,"pause":pause,"restore":restore,"watchdog":watchdog}[a.mode]()
 except Exception as e:
  msg=str(e)
  # Built-in API error identifiers contain lower-case Worker names. Expose
  # only these known diagnostics, never untrusted HTTP bodies or credentials.
  known_error=bool(re.fullmatch(r"CF_(GET|PUT)_rasha-goodbye-(video-scanner|air-alerts|content-hub)_(HTTP_[0-9]{3}|NETWORK_UNCERTAIN|CURL_[A-Z_]+|ERROR)",msg))
  safe=msg if known_error or re.fullmatch(r"[A-Z0-9_]{3,110}",msg) else type(e).__name__
  emit("BLOCKED",reason=safe)
  sys.exit(1)
