#!/bin/sh
# RG Telegram V24 - Content Hub diagnostic. Only authenticated admin GETs.
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
  ("SCHEDULED_SLOT_NOT_CONFIRMED",r"scheduled_content_slot_not_confirmed"),
  ("SLOT_STALE_BEFORE_SEND",r"slot_became_stale_before_send|staleslot"),
  ("RECOVERY_WINDOW_EXPIRED",r"recovery_window_expired"),
  ("PUBLICATION_UNCERTAIN",r"uncertain|ambiguous"),
  ("MEDIA_POLICY",r"photo.required|image.required|watermark|placeholder|safety"),
  ("HTTP_403",r"\b403\b"),("HTTP_429",r"\b429\b"),
  ("HTTP_5XX",r"\b5[0-9]{2}\b"),
  ("RSS_FETCH_FAILURE",r"rss|feed|source[_ -]?error"),
  ("TIMEOUT",r"timed out|timeout"),
  ("NETWORK",r"network|connection|dns|fetch failed"),
 ]
 for label,pattern in patterns:
  if re.search(pattern,s):return label
 return "OTHER_REDACTED"
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
print("=== RG TELEGRAM V24 CONTENT HUB READ ONLY ===")
print("KYIV_DATE",today)
for k in ("last_deploy_status","deploy_stage","telegram_watchdog_status","scheduler_last_check_status"):
 print("NAS",k,token(read(state/k,100)))
sha=read(state/"last_deployed_sha",100)
print("PROVENANCE","R7_SHA_MATCHES",flag(sha==R7))
h,c=get("/content")
entries=c.get("state") if isinstance(c.get("state"),dict) else {}
health=entries.get("content-hub-health-v2") if isinstance(entries.get("content-hub-health-v2"),dict) else {}
content=entries.get("content-hub-state-v2") if isinstance(entries.get("content-hub-state-v2"),dict) else {}
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
 print("CONTENT_SLOT",mode,"health_status",token(row.get("status")),
  "sent_record",flag(bool(mark)), "sent_has_telegram_message_id",flag(bool(mark.get("messageId"))),
  "missed_record",flag(bool(miss)), "uncertain",flag(att.get("uncertain") is True),
  "attempt_error_class",classified(att.get("lastError") or miss.get("lastError") or row.get("lastError")),
  "next_attempt_age_sec",age(att.get("nextAttemptAt")))
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
print("SCOPE","GET_ONLY_NO_ACTIONS_NO_MESSAGE_CONTENT")
print("RG_TELEGRAM_V24_COMPLETE_READ_ONLY")
PY
