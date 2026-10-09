#!/bin/sh
# RG Telegram R8 - Content Hub and cron evidence diagnostic. Only authenticated admin GETs.
# No scheduling, retries, publication, scanner, AI calls, or queue mutation.
set -eu
[ "$(id -u)" = "0" ] || { echo "SUDO_REQUIRED"; exit 2; }
python3 - <<'PY'
import collections,datetime,json,re,shutil,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
try:
 from zoneinfo import ZoneInfo
 kyiv=datetime.datetime.now(ZoneInfo("Europe/Kyiv"))
except Exception:
 kyiv=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
today=kyiv.date().isoformat()
now=time.time()
root=Path("/volume1/docker")
state=root/"RG_NAS_STATE"
R7="ee1f3ed8e7b567df37e3addda066c49a41996be3"
def read(path,cap=4096):
 try:
  if path.is_symlink() or not path.is_file() or path.stat().st_size>cap:return None
  return path.read_text(encoding="utf8",errors="replace").strip()
 except OSError:return None
def token(v):return v if isinstance(v,str) and re.fullmatch("[A-Za-z0-9_.:-]{1,60}",v) else "UNKNOWN"
def flag(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def count(v):
 try:
  if isinstance(v,bool):return "UNKNOWN"
  n=int(v)
  return n if 0<=n<=1000000 else "UNKNOWN"
 except (ValueError,TypeError):return "UNKNOWN"
def age(v):
 try:
  parsed=datetime.datetime.fromisoformat(str(v).replace("Z","+00:00"))
  if not parsed.tzinfo:return "UNKNOWN"
  return max(0,round(now-parsed.timestamp()))
 except (ValueError,TypeError):return "UNKNOWN"
def classified(v):
 s=str(v or "").lower()
 if not s:return "NONE"
 patterns=[
  ("AI_DEFER_SHARED_DAILY_BUDGET",r"ai_defer:shared_daily_budget"),
  ("AI_DEFER_CONTENT_DAILY_BUDGET",r"ai_defer:content_daily_budget"),
  ("AI_DEFER_PROVIDER_COOLDOWN",r"ai_defer:ai_rate_limit_cooldown"),
  ("AI_DEFER_MODE_DISALLOWED",r"ai_defer:content_mode_uses_deterministic_fallback"),
  ("AI_DEFER",r"ai_defer"),
  ("AI_BUDGET",r"(?:ai|quota|budget).{0,35}(?:exhaust|limit|cooldown|defer|reserve)|(?:exhaust|limit|cooldown|defer).{0,35}(?:ai|quota|budget)"),
  ("GEMINI_HTTP_400",r"gemini.{0,90}\bhttp 400\b"),
  ("GEMINI_HTTP_401_403",r"gemini.{0,90}\bhttp (?:401|403)\b"),
  ("GEMINI_HTTP_429",r"gemini.{0,90}\bhttp 429\b"),
  ("GEMINI_HTTP_5XX",r"gemini.{0,90}\bhttp 5[0-9]{2}\b"),
  ("GEMINI_BAD_RESPONSE",r"gemini.{0,100}(?:malformed json|empty output|status=|invalid response)"),
  ("INVALID_EXPLAINER_OUTPUT",r"invalid explainer output"),
  ("EXPLAINER_CAPTION_TOO_LONG",r"explainer caption too long"),
  ("NO_PUBLISHABLE_CONTENT",r"no publishable content"),
  ("CONTENT_VALIDATION",r"caption.{0,50}(?:invalid|too long|bad)|invalid.{0,50}caption|scheduled_publication"),
  ("STALE_SLOT",r"stale_content_slot|slot_became_stale_before_send"),
  ("RECOVERY_WINDOW_EXPIRED",r"recovery_window_expired"),
  ("PUBLICATION_UNCERTAIN",r"publication.{0,25}uncertain|ambiguous.{0,40}(?:telegram|publication)"),
  ("TELEGRAM_HTTP_400",r"telegram.{0,70}\b(?:http\s*)?400\b"),
  ("TELEGRAM_HTTP_401_403",r"telegram.{0,70}\b(?:http\s*)?(?:401|403)\b"),
  ("TELEGRAM_HTTP_429",r"telegram.{0,70}\b(?:http\s*)?429\b"),
  ("TELEGRAM_HTTP_5XX",r"telegram.{0,70}\b(?:http\s*)?5[0-9]{2}\b"),
  ("PHOTO_OR_MEDIA",r"(?:image|photo|media).{0,40}(?:fail|missing|blocked|not verified|invalid|unavail)|(?:fail|missing|blocked).{0,30}(?:image|photo|media)"),
  ("RSS_FETCH",r"(?:rss|feed|source).{0,30}(?:fail|unavail|error|http)"),
  ("TIMEOUT",r"timed out|timeout|aborterror"),
  ("NETWORK",r"network|connection|dns|fetch failed"),
 ]
 for label,pat in patterns:
  if re.search(pat,s):return label
 return "OTHER_REDACTED"
def iso_sec(v):
 try:
  dt=datetime.datetime.fromisoformat(str(v).replace("Z","+00:00"))
  return dt.timestamp() if dt.tzinfo else None
 except (ValueError,TypeError):return None
def timing(v):
 ts=iso_sec(v)
 if ts is None:return "UNKNOWN", "UNKNOWN"
 lag=ts-now
 return ("DUE",max(0,round(-lag))) if lag<=0 else ("WAITING",max(0,round(lag)))
url=read(root/"RG_NAS_CONTROL/admin_url",1024)
secret=read(root/"RG_SECRETS/rg_admin_token",4096)
parsed=urlsplit(url or "")
if not url or not secret or parsed.scheme not in ("https","http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme=="http" and parsed.hostname not in ("localhost","127.0.0.1")) or not re.fullmatch(r"[A-Za-z0-9_.~+/=-]{8,4096}",secret):
 print("ADMIN_CONFIG_UNAVAILABLE");raise SystemExit(1)
curl=shutil.which("curl")
if not curl:print("CURL_MISSING");raise SystemExit(1)
config='header = "Authorization: Bearer '+secret+'"\nconnect-timeout = 8\nmax-time = 20\n'
def get(path):
 try:
  result=subprocess.run([curl,"--silent","--show-error","--config","-",
     "--max-filesize","15000000","--write-out","\nCODE:%{http_code}",url.rstrip("/")+path],
    input=config.encode(),capture_output=True,timeout=25)
  marker=b"\nCODE:"
  if result.returncode or marker not in result.stdout:return "ERROR",{}
  raw,code=result.stdout.rsplit(marker,1)
  obj=json.loads(raw)
  return code.decode("ascii","replace").strip(),obj if isinstance(obj,dict) else {}
 except (OSError,ValueError,subprocess.TimeoutExpired):return "ERROR",{}
print("=== RG TELEGRAM R8 CRON EVIDENCE READ ONLY ===")
print("KYIV_DATE",today)
for k in ("last_deploy_status","deploy_stage","telegram_watchdog_status","scheduler_last_check_status"):
 print("NAS",k,token(read(state/k,100)))
sha=read(state/"last_deployed_sha",100)
print("PROVENANCE","R7_SHA_MATCHES",flag(sha==R7))
h,c=get("/content")
entries=c.get("state") if isinstance(c.get("state"),dict) else {}
health=entries.get("content-hub-health-v2") if isinstance(entries.get("content-hub-health-v2"),dict) else {}
content=entries.get("content-hub-state-v2") if isinstance(entries.get("content-hub-state-v2"),dict) else {}
content_health=health
print("CONTENT_HEALTH","http",h,
 "ok",flag(health.get("ok")),
 "age_sec",age(health.get("checkedAt") or health.get("updatedAt")),
 "today",flag(health.get("dateKey")==today),
 "last_outcome",token(health.get("lastOutcome")),
 "error_class",classified(health.get("error")),
 "scheduler_alive",flag(health.get("schedulerAlive")),
 "build_matches_R7",flag(health.get("buildSha")==R7))
readiness=health.get("slotReadiness") if isinstance(health.get("slotReadiness"),dict) else {}
slots=readiness.get("slots") if isinstance(readiness.get("slots"),dict) else {}
sent=content.get("sent") if isinstance(content.get("sent"),dict) else {}
missed=content.get("missed") if isinstance(content.get("missed"),dict) else {}
attempts=content.get("attempts") if isinstance(content.get("attempts"),dict) else {}
print("SLOT_READINESS","ok",flag(readiness.get("ok")),"date_matches",flag(readiness.get("dateKey")==today),
 "checked_age_sec",age(readiness.get("checkedAt")))
for mode in ("morning","poll","explain","evening"):
 key=today+":"+mode
 row=slots.get(mode) if isinstance(slots.get(mode),dict) else {}
 mark=sent.get(key) if isinstance(sent.get(key),dict) else {}
 miss=missed.get(key) if isinstance(missed.get(key),dict) else {}
 att=attempts.get(key) if isinstance(attempts.get(key),dict) else {}
 due_state,due_sec=timing(att.get("nextAttemptAt"))
 print("CONTENT_SLOT",mode,"health_status",token(row.get("status")),
  "sent_record",flag(bool(mark)), "sent_has_telegram_message_id",flag(bool(mark.get("messageId"))),
  "missed_record",flag(bool(miss)), "uncertain",flag(att.get("uncertain") is True),
  "attempt_error_class",classified(att.get("lastError") or miss.get("lastError") or row.get("lastError")),
  "last_attempt_age_sec",age(att.get("lastAttemptAt")),
  "next_retry",due_state,"retry_seconds",due_sec)
journal=content.get("journal") if isinstance(content.get("journal"),list) else []
classes=collections.Counter(
 token(x.get("type")) for x in journal
 if isinstance(x,dict) and x.get("date")==today
)
print("JOURNAL_TODAY","visible_rows",sum(classes.values()),
 "classes",json.dumps(dict(classes.most_common(12)),sort_keys=True))
x,system=get("/production-state")
prod=system.get("productionReadiness") if isinstance(system.get("productionReadiness"),dict) else {}
print("PRODUCTION","http",x,"ready",flag(system.get("ok")),"blocking_stage",token(prod.get("blockingStage")))
print("PRODUCTION_DETAIL","blocked_stage",token(prod.get("blockingStage")),
 "blocked_reason",token(prod.get("blockingDetail")) if token(prod.get("blockingDetail"))!="UNKNOWN" else classified(prod.get("blockingDetail")))
for row in prod.get("stages",[]) if isinstance(prod.get("stages"),list) else []:
 if not isinstance(row,dict):continue
 kind=str(row.get("id") or "")
 if kind not in ("scanner","moderation","media","publish","receipt","schedule","alerts","nas"):continue
 detail=str(row.get("detail") or "")
 print("CHAIN_STAGE",kind,"ok",flag(row.get("ok")),
  "reason",token(detail) if token(detail)!="UNKNOWN" else classified(detail))
moder=system.get("status",{}).get("telegram-video-moderation-health-v2",{}) if isinstance(system.get("status"),dict) else {}
moder=moder if isinstance(moder,dict) else {}
print("MODERATION_LIVE","ok",flag(moder.get("ok")),"degraded",flag(moder.get("degraded")),
 "offset_blocked",flag(moder.get("offsetBlocked")),"updates_failed",count(moder.get("updatesFailed")),
 "age_sec",age(moder.get("liveCheckedAt") or moder.get("checkedAt") or moder.get("updatedAt")),
 "error_class",classified(moder.get("error") or moder.get("degradedReason")))
queues=system.get("queues") if isinstance(system.get("queues"),dict) else {}
health=queues.get("telegram-moderation-publish-health-v2") if isinstance(queues.get("telegram-moderation-publish-health-v2"),dict) else {}
print("PUBLISH_LIVE","age_sec",age(health.get("updatedAt") or health.get("lastRunAt") or health.get("checkedAt")),
 "failed_today",count(health.get("failed")),"uncertain_today",count(health.get("uncertain")),
 "health_date_matches",flag(health.get("dateKey")==today))
print("SOURCE_AI_GATE","automatic_daily_cap",10,"content_daily_cap",10,
 "no_generation_on_defer", "EXPECTED_POLICY_NOT_RUNTIME_VERIFIED")

# R8: passive cron evidence from Content Hub. No writes or external calls beyond the V26 GETs.
# This intentionally distinguishes schedulerAlive from confirmed scheduled-handler execution.
cron_fields=("lastCronAt","lastCronRunAt","cronLastRunAt","lastScheduledAt","lastScheduledRunAt",
             "lastCronSuccessAt","cronLastSuccessAt","scheduledHandlerLastRunAt")
cron_sources=[("health",content_health),("content",content)]
evidence=[]
for source,obj in cron_sources:
 if not isinstance(obj,dict):continue
 for key in cron_fields:
  value=obj.get(key)
  sec=age(value)
  if sec!="UNKNOWN":
   evidence.append((source,key,sec))
if evidence:
 for source,key,sec in evidence:
  print("CRON_EVIDENCE","source",source,"field",key,"age_sec",sec)
else:
 print("CRON_EVIDENCE","UNKNOWN","reason","NO_EXPLICIT_CRON_TIMESTAMP_IN_EXPOSED_STATE")
print("CRON_CONCLUSION","UNVERIFIED","reason","CLOUDFLARE_EXECUTION_LOGS_NOT_EXPOSED")
print("AI_DEFER_POLICY","EXPECTED_NOT_VERIFIED")

# R8: avoid inferring the alert delivery state from scheduler freshness.
print("ALERTS_VERIFICATION","UNVERIFIED","reason","DIRECT_ALERT_API_NOT_QUERIED")
print("MODERATION_VERIFICATION","UNVERIFIED_IF_STALE","reason","CHECK_LIVE_AGE_AND_WATCHDOG")
print("CLOUDFLARE_LOG_VERIFICATION","UNVERIFIED","reason","REQUIRES_WORKER_OBSERVABILITY")

print("SCOPE","GET_ONLY_NO_ACTIONS_NO_MESSAGE_CONTENT")
print("RG_TELEGRAM_R8_COMPLETE_READ_ONLY")
PY
