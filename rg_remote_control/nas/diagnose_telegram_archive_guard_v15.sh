#!/bin/sh
# RG Telegram V13 release + visual verification report, read-only.
# No deploy, publishing, scanner runs, queue edits, or Telegram requests.
set -eu
[ "$(id -u)" = "0" ] || { echo "Run with sudo sh"; exit 2; }
python3 - <<'PY'
import datetime,json,re,shutil,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
R=Path("/volume1/docker");S=R/"RG_NAS_STATE"
EXPECTED="b3e92b6a243434c6dd53f8304a42e7385d893e52"
now=time.time()
def read(p,limit=4096):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return None
  return p.read_text(encoding="utf-8",errors="replace").strip()
 except OSError:return None
def obj(v):return v if isinstance(v,dict) else {}
def n(v):
 try:return int(v) if type(v)==int and 0<=v<10000000 else 0
 except (TypeError,ValueError):return 0
def age(p):
 try:return max(0,int(now-p.stat().st_mtime))
 except OSError:return "UNKNOWN"
def val(v):
 if v is None:return "MISSING"
 if isinstance(v,str) and re.fullmatch("[A-Za-z0-9_.:-]{1,90}",v):return v
 return "OTHER"
def boolean(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def time_age(v):
 try:
  x=datetime.datetime.fromisoformat(str(v).replace("Z","+00:00"))
  return max(0,int(now-x.timestamp())) if x.tzinfo else "UNKNOWN"
 except (TypeError,ValueError):return "UNKNOWN"
print("=== RG TELEGRAM V15 RELEASE + GEMINI (READ ONLY) ===",flush=True)
print("EXPECTED_GITHUB_SHA",EXPECTED[:12])
for k in ("last_deploy_status","deploy_stage","deploy_sync_status","live_smoke_status",
          "scheduler_last_check_status","telegram_startup_selftest_status",
          "telegram_control_plane_status","telegram_watchdog_status"):
 p=S/k;print("STATE",k,val(read(p,120)),"age_sec",age(p),flush=True)
for name in ("last_deployed_sha","last_synced_head_sha","last_video_deployed_sha",
             "last_control_plane_sha","last_control_app_sha","live_smoke_sha"):
 x=read(S/name,130)
 print("PROVENANCE",name,"matches_expected",boolean(x==EXPECTED),"sha_prefix",(x[:12] if x and re.fullmatch("[0-9a-fA-F]{40}",x) else "UNKNOWN"))
release=R/"RG_RELEASES/telegram-control"
m=release/"current-release-manifest.json";p=release/"current-release-source.json"
print("ACTIVE_RELEASE_FILES",boolean(m.is_file() and p.is_file()),"manifest_age_sec",age(m),"source_age_sec",age(p))
def load_file(path):
 try:
  if path.is_symlink() or path.stat().st_size>1000000:return {}
  return obj(json.loads(path.read_text(encoding="utf8")))
 except (OSError,ValueError):return {}
active=load_file(p)
print("ACTIVE_RELEASE", "active",boolean(active.get("active")),"sha_matches_expected",boolean(active.get("sourceSha")==EXPECTED))
details=read(S/"selftest_details",30000) or ""
for line in details.splitlines():
 if "❌" in line:
  lab=line.split("❌",1)[1].strip()
  if re.fullmatch(r"[\w .:/()-]{1,100}",lab):
   print("SELFTEST_FAILED",lab)
watch=load_file(S/"telegram-watchdog-status.json")
print("WATCHDOG_REPORT","age_sec",age(S/"telegram-watchdog-status.json"),"ok",boolean(watch.get("ok")),"issues_count",n(len(watch.get("issues",[])) if isinstance(watch.get("issues"),list) else 0))
for issue in (watch.get("issues") if isinstance(watch.get("issues"),list) else [])[:10]:
 print("WATCHDOG_ISSUE",val(issue))
url=read(R/"RG_NAS_CONTROL/admin_url",1024)
secret=read(R/"RG_SECRETS/rg_admin_token",4096)
u=urlsplit(url or "")
if not url or not secret or u.scheme not in ("https","http") or not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme=="http" and u.hostname not in ("localhost","127.0.0.1")) or not re.fullmatch(r"[A-Za-z0-9_.~+/=-]{8,4096}",secret):
 print("ADMIN_CONFIG_UNAVAILABLE");raise SystemExit(1)
curl=shutil.which("curl")
if not curl:print("CURL_NOT_FOUND");raise SystemExit(1)
config='header = "Authorization: Bearer '+secret+'"\nconnect-timeout = 8\nmax-time = 22\n'
def fetch(path):
 try:
  p=subprocess.run([curl,"--silent","--show-error","--config","-","--max-filesize","15000000","--write-out","\nHTTP_CODE:%{http_code}",url.rstrip("/")+path],input=config.encode(),capture_output=True,timeout=28)
  marker=b"\nHTTP_CODE:"
  if marker not in p.stdout:return "UNKNOWN",{}
  raw,code=p.stdout.rsplit(marker,1)
  try:body=obj(json.loads(raw))
  except (ValueError,UnicodeError):body={}
  return code.decode("ascii","replace").strip(),body
 except (OSError,subprocess.TimeoutExpired):return "UNKNOWN",{}
http,status=fetch("/status")
scanner=obj(obj(status.get("state")).get("telegram-video-scanner-health-v3"))
visual=obj(scanner.get("visualTelemetry"))
print("SCANNER_HTTP",http,"scanner_ok",boolean(scanner.get("ok")),"checked_age_sec",time_age(scanner.get("checkedAt")))
print("VISUAL","available",boolean("visualTelemetry" in scanner),"verified_live",n(visual.get("verifiedLive")),"verified_cache",n(visual.get("verifiedCache")),"unverified",n(visual.get("unverified")),"http400",n(visual.get("http400")))

arc=obj(scanner.get("deadLetterArchive"))
print("ARCHIVE_OPERATION","present",boolean("deadLetterArchive" in scanner),"ok",boolean(arc.get("ok")),
 "archived",n(arc.get("archived")),"remaining",n(arc.get("remaining")),
 "newly_stored",n(arc.get("newlyStored")),"error_class",
 str(arc.get("error")) if str(arc.get("error")) in (
 "atomic_archive_unavailable","archive_migration_not_ready","active_invalid_shape",
 "archive_invalid_shape","archive_capacity_guard") else "NONE_OR_OTHER")

if not visual:print("VISUAL_PROOF","NOT_AVAILABLE_OR_NO_SCANNER_CYCLE_AFTER_ROLLOUT")
elif n(visual.get("verifiedLive"))>0:print("VISUAL_PROOF","NEW_LIVE_GEMINI_CHECK_VERIFIED_THIS_CYCLE")
elif n(visual.get("unverified"))>0:print("VISUAL_PROOF","VISUAL_CHECK_ATTEMPTED_BUT_NOT_VERIFIED")
else:print("VISUAL_PROOF","NO_NEW_LIVE_GEMINI_SUCCESS_THIS_CYCLE")
qhttp,qbody=fetch("/queues")
dead=obj(qbody.get("state")).get("telegram-video-dead-letter-v1")
entries=dead.get("items") if isinstance(dead,dict) else dead if isinstance(dead,list) else []
if not isinstance(entries,list):entries=[]
print("DEAD_LETTER","http",qhttp,"count",len(entries),"historical_over_4h",sum(1 for i in entries if isinstance(i,dict) and isinstance(i.get("at"),str) and isinstance(time_age(i["at"]),int) and time_age(i["at"])>4*3600))

for i,item in enumerate(entries[:3],1):
 if not isinstance(item,dict):continue
 key=str(item.get("key") or "")
 reason=str(item.get("reason") or "")
 at=time_age(item.get("at"))
 attempts=n(item.get("attempts"))
 link=str(item.get("sourceUrl") or "")
 print("ACTIVE_RECORD_ELIGIBILITY",i,"key_valid",boolean(re.fullmatch("[a-f0-9]{12}",key) is not None),
 "reason_visual_http400",boolean(re.fullmatch("visual:[a-z0-9.-]+_http_400",reason,re.I) is not None),
 "link_valid",boolean(re.fullmatch("https?://t[.]me/[A-Za-z0-9_]{4,}/[0-9]+",link,re.I) is not None),
 "age_hours",(at//3600 if isinstance(at,int) else "UNKNOWN"),"attempts",attempts,
 "would_match_archive_rule",boolean(
 re.fullmatch("[a-f0-9]{12}",key) is not None and
 re.fullmatch("visual:[a-z0-9.-]+_http_400",reason,re.I) is not None and
 re.fullmatch("https?://t[.]me/[A-Za-z0-9_]{4,}/[0-9]+",link,re.I) is not None and
 isinstance(at,int) and at>=4*3600 and attempts>=8))


archive=obj(qbody.get("state")).get("telegram-video-dead-letter-archive-v1")
archived=archive.get("items") if isinstance(archive,dict) else archive if isinstance(archive,list) else []
if not isinstance(archived,list):archived=[]
valid=[]
for item in archived:
 if not isinstance(item,dict):continue
 linked=re.fullmatch(r"https?://t[.]me/[A-Za-z0-9_]{4,}/[0-9]+",str(item.get("sourceUrl") or "")) is not None
 reason=str(item.get("reason") or "")
 valid.append(
  item.get("archiveReason")=="historical_terminal_visual_http_400" and
  item.get("publicationEligible") is False and item.get("autoRetry") is False and
  linked and str(item.get("key") or "")!="" and
  reason.startswith("visual:") and reason.endswith("_http_400") and
  n(item.get("attempts"))>=8 and bool(item.get("at")) and bool(item.get("archivedAt"))
 )
print("ARCHIVE","records",len(archived),"audited_terminal_records",sum(valid),"record_integrity_ok",boolean(bool(archived) and all(valid)))

prodhttp,prod=fetch("/production-state")
readiness=obj(prod.get("productionReadiness"))
print("PRODUCTION_READINESS","http",prodhttp,"ok",boolean(prod.get("ok")),"blocked_stage",val(readiness.get("blockingStage")))
for stage in (readiness.get("stages") if isinstance(readiness.get("stages"),list) else [])[:10]:
 if isinstance(stage,dict) and stage.get("ok") is not True:
  print("BLOCKER","id",val(stage.get("id")),"detail",val(stage.get("detail")))
print("FINAL","dead_letter_cleared",boolean(len(entries)==0),"historical_archive_verified",boolean(bool(archived) and all(valid)),"production_ready",boolean(prod.get("ok")))
print("RG_TELEGRAM_V15_COMPLETE_READ_ONLY",flush=True)
PY
