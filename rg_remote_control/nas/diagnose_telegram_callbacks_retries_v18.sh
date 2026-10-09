#!/bin/sh
# RG Telegram V18: nonpublishing callback + publish-retry audit (read-only).
# Only authenticated GET calls to existing admin endpoints. No queue updates,
# no replay, no scanner invocation, no Telegram or AI requests.
set -eu
[ "$(id -u)" = "0" ] || { echo "Requires sudo sh"; exit 2; }
python3 - <<'PY'
import datetime,json,re,shutil,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
try:
 from zoneinfo import ZoneInfo
 local=datetime.datetime.now(ZoneInfo("Europe/Kyiv"))
except Exception:
 local=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
today=local.date().isoformat()
now=time.time()
R=Path("/volume1/docker")
def read(path,limit):
 try:
  if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:return None
  return path.read_text(encoding="utf8",errors="replace").strip()
 except OSError:return None
def safe(v):
 s=str(v) if v is not None else ""
 return s if re.fullmatch(r"[A-Za-z0-9_.:-]{1,70}",s) else "UNKNOWN"
def status(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def count(v):
 try:
  x=int(v)
  return x if 0<=x<=1000000 else "UNKNOWN"
 except (ValueError,TypeError):return "UNKNOWN"
def when(v):
 try:
  d=datetime.datetime.fromisoformat(str(v).replace("Z","+00:00"))
  return d.timestamp() if d.tzinfo else None
 except (TypeError,ValueError):return None
def age(v):
 d=when(v)
 return max(0,round(now-d)) if d is not None else "UNKNOWN"
def classify_error(value):
 s=str(value or "").lower()
 if not s:return "NONE"
 patterns=[
  ("HTTP_400",r"\b(?:http[_ ]?|status[_ ]?)400\b"),("HTTP_401",r"\b(?:http[_ ]?|status[_ ]?)401\b"),
  ("HTTP_403",r"\b(?:http[_ ]?|status[_ ]?)403\b"),("HTTP_404",r"\b(?:http[_ ]?|status[_ ]?)404\b"),
  ("HTTP_409",r"\b(?:http[_ ]?|status[_ ]?)409\b"),("HTTP_429",r"\b(?:http[_ ]?|status[_ ]?)429\b"),
  ("HTTP_5XX",r"\b(?:http[_ ]?|status[_ ]?)5[0-9]{2}\b"),
  ("LEASE_WAIT",r"\blease\b|\bbusy\b"),("TIMEOUT",r"timeout|timed out"),
  ("MESSAGE_NOT_FOUND",r"message.*not found|not found|expired"),
  ("MEDIA_POLICY",r"media.policy|watermark|without photo|no photo|image required"),
  ("DUPLICATE",r"duplicate|already (?:used|published|exists)"),
  ("CALLBACK_INVALID",r"callback.*invalid|invalid.*callback|query.*invalid"),
  ("NETWORK",r"network|fetch failed|connection|dns"),
 ]
 for name,pat in patterns:
  if re.search(pat,s):return name
 return "OTHER_REDACTED"
def callback_action(v):
 s=str(v or "")
 if not s:return "UNKNOWN"
 for x in ("approve","reject","publish_retry","publish_cancel","watermark","clear","recheck"):
  if re.search(r"(?<![a-z_])"+re.escape(x)+r"(?=:|$)",s,re.I):return x.upper()
 return "OTHER_REDACTED"
url=read(R/"RG_NAS_CONTROL/admin_url",1024)
token=read(R/"RG_SECRETS/rg_admin_token",4096)
u=urlsplit(url or "")
if not url or not token or u.scheme not in ("https","http") or not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme=="http" and u.hostname not in ("localhost","127.0.0.1")) or not re.fullmatch("[A-Za-z0-9_.~+/=-]{8,4096}",token):
 print("ADMIN_CONFIG_UNAVAILABLE");raise SystemExit(1)
curl=shutil.which("curl")
if not curl:print("CURL_MISSING");raise SystemExit(1)
config='header = "Authorization: Bearer '+token+'"\nconnect-timeout = 8\nmax-time = 20\n'
def get(path):
 try:
  p=subprocess.run([curl,"--silent","--show-error","--config","-","--max-filesize","9000000","--write-out","\nCODE:%{http_code}",url.rstrip("/")+path],
   input=config.encode(),capture_output=True,timeout=25)
  marker=b"\nCODE:"
  if p.returncode or marker not in p.stdout:return "ERROR",{}
  raw,code=p.stdout.rsplit(marker,1)
  data=json.loads(raw)
  return code.decode("ascii","replace").strip(), data if isinstance(data,dict) else {}
 except (OSError,ValueError,subprocess.TimeoutExpired):return "ERROR",{}
print("=== RG TELEGRAM V18 CALLBACK / PUBLICATION RETRY / OPEN ITEMS - READ ONLY ===",flush=True)
print("KYIV_DATE",today)
h,d=get("/moderation-debug?date="+today)
callbacks=d.get("callbacks") if isinstance(d.get("callbacks"),dict) else {}
health=d.get("publishHealth") if isinstance(d.get("publishHealth"),dict) else {}
journal=d.get("publicationJournal") if isinstance(d.get("publicationJournal"),dict) else {}
print("DEBUG_HTTP",h,"date_matches",status(d.get("dateKey")==today))
print("CALLBACKS_CUMULATIVE_TODAY",
 "fetched",count(callbacks.get("fetched")),"processed",count(callbacks.get("processed")),
 "failed",count(callbacks.get("failed")),"unsupported",count(callbacks.get("unsupported")),
 "decisions",count(callbacks.get("decisions")),"poll_busy",count(callbacks.get("pollBusy")),
 "last_failure_age_sec",age(callbacks.get("lastFailureAt")),
 "last_failure_class",classify_error(callbacks.get("lastFailedError")),
 "failed_action",callback_action(callbacks.get("lastFailedCallbackData")),
 "last_decision_age_sec",age(callbacks.get("lastDecisionAt")))
print("PUBLISH_HEALTH_TODAY","date_matches",status(health.get("dateKey")==today),
 "published",count(health.get("published")),"retries",count(health.get("retries")),
 "failed",count(health.get("failed")),"uncertain",count(health.get("uncertain")),
 "blocked",count(health.get("blocked")),"queued",count(health.get("queued")),
 "last_check_age_sec",age(health.get("updatedAt") or health.get("lastRunAt")))
rows=journal.get("items") if isinstance(journal.get("items"),list) else []
def published_today(item):
 ts=when(item.get("publishedAt")) if isinstance(item,dict) else None
 if ts is None:return False
 return datetime.datetime.fromtimestamp(ts,local.tzinfo).date().isoformat()==today
today_rows=[r for r in rows if isinstance(r,dict) and published_today(r)]
print("PUBLICATION_JOURNAL_LAST20","total_rows",len(rows),"today_rows",len(today_rows),
 "today_with_message_id",sum(1 for r in today_rows if r.get("messageId") is not None))
qh,q=get("/queues")
state=q.get("state") if isinstance(q.get("state"),dict) else {}
pq=state.get("telegram-moderation-publish-queue-v2")
keys=pq.get("keys") if isinstance(pq,dict) and isinstance(pq.get("keys"),list) else []
print("PUBLISH_QUEUE","http",qh,"queued",len(keys),"snapshot_present",status(pq is not None))
filters=["open","publish_retry","publish_pending","publish_uncertain","publish_failed"]
for filter_name in filters:
 code,doc=get("/moderation-candidates?status="+filter_name+"&limit=80")
 items=doc.get("items") if isinstance(doc.get("items"),list) else []
 print("CANDIDATE_FILTER","status",filter_name,"http",code,
       "matched",count(doc.get("matched")),"scanned",count(doc.get("scanned")),
       "returned",len(items))
 if filter_name=="publish_retry":
  for i,item in enumerate(items[:5],1):
   if not isinstance(item,dict):continue
   pkey=str(item.get("key") or "")
   deadline=when(item.get("publishNextAttemptAt"))
   timing="UNKNOWN" if deadline is None else "DUE" if deadline<=now else "FUTURE"
   stage=safe(item.get("publishStage"))
   approved=bool(item.get("publishedAt")) or bool(item.get("publishedMessageId"))
   print("RETRY_ITEM",i,
         "publish_attempts",count(item.get("publishAttempts")),
         "stage",stage,
         "retry_timing",timing,
         "retry_due_age_sec",(max(0,int(now-deadline)) if deadline is not None and deadline<=now else "NOT_DUE"),
         "created_age_sec",age(item.get("createdAt")),
         "decided_age_sec",age(item.get("decidedAt")),
         "in_publish_queue",status(pkey in keys),
         "already_has_delivery_evidence",status(approved),
         "last_error_class",classify_error(item.get("publishLastError")))
 if filter_name=="open":
  print("OPEN_MODERATION", "waiting_card_count",len(items),
        "with_message_id",sum(1 for item in items if isinstance(item,dict) and item.get("moderatorMessageId") is not None))
shttp,sdoc=get("/status")
st=sdoc.get("state") if isinstance(sdoc.get("state"),dict) else {}
mod=st.get("telegram-video-moderation-health-v2") if isinstance(st.get("telegram-video-moderation-health-v2"),dict) else {}
scan=st.get("telegram-video-scanner-health-v3") if isinstance(st.get("telegram-video-scanner-health-v3"),dict) else {}
daily=scan.get("dailyMetrics") if isinstance(scan.get("dailyMetrics"),dict) else {}
print("CURRENT_HEALTH","http",shttp,"moderation_ok",status(mod.get("ok")),
 "moderation_failed_last_poll",count(mod.get("updatesFailed")),
 "scanner_ok",status(scan.get("ok")),
 "scanner_last_cycle_delivery_errors",len(scan.get("batch",{}).get("failures",[])) if isinstance(scan.get("batch"),dict) and isinstance(scan.get("batch",{}).get("failures"),list) else "UNKNOWN",
 "historical_delivery_failures_today",count(daily.get("deliveryFailures")) if daily.get("dateKey")==today else "UNKNOWN")
phttp,prod=get("/production-state")
print("PRODUCTION_READINESS","http",phttp,"ready",status(prod.get("ok")))
print("AUDIT_SCOPE","GET_ONLY_NO_PUBLICATION_NO_REPLAY")
print("RG_TELEGRAM_V18_COMPLETE_READ_ONLY")
PY
