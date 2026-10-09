#!/bin/sh
# RG Telegram V17 - nonpublishing delivery audit. Strictly read-only.
# Only admin GET endpoints are used; no Telegram API, deploy, AI, scheduler,
# moderation actions, queue mutation or watchdog invocation.
set -eu
[ "$(id -u)" = "0" ] || { echo "Run with sudo sh"; exit 2; }
python3 - <<'PY'
import collections,datetime,json,re,shutil,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
try:
 from zoneinfo import ZoneInfo
 kyiv=datetime.datetime.now(ZoneInfo("Europe/Kyiv"))
except ImportError:
 kyiv=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
today=kyiv.date().isoformat()
now=time.time()
root=Path("/volume1/docker")
def text_file(path,limit):
 try:
  p=Path(path)
  if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return None
  return p.read_text(encoding="utf8",errors="replace").strip()
 except OSError:return None
def obj(v):return v if isinstance(v,dict) else {}
def safe(v):
 if v is None:return "UNKNOWN"
 s=str(v)
 return s if re.fullmatch(r"[A-Za-z0-9_.:-]{1,65}",s) else "OTHER"
def truth(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def num(v):
 try:
  x=int(v)
  return x if 0<=x<=10000000 else "UNKNOWN"
 except (ValueError,TypeError):return "UNKNOWN"
def age(v):
 try:
  x=datetime.datetime.fromisoformat(str(v).replace("Z","+00:00"))
  return max(0,int(now-x.timestamp())) if x.tzinfo else "UNKNOWN"
 except (ValueError,TypeError):return "UNKNOWN"
def day(v):
 try:
  x=datetime.datetime.fromisoformat(str(v).replace("Z","+00:00"))
  return x.astimezone(kyiv.tzinfo).date().isoformat() if x.tzinfo else "UNKNOWN"
 except (ValueError,TypeError):return "UNKNOWN"
def count_queue(v):
 if isinstance(v,list):return len(v)
 if not isinstance(v,dict):return "UNKNOWN"
 for key in ("keys","items"):
  if isinstance(v.get(key),list):return len(v[key])
 for key in ("queued","count","size","length","remaining"):
  if type(v.get(key)) is int:return num(v[key])
 return "UNKNOWN"
url=text_file(root/"RG_NAS_CONTROL/admin_url",1024)
secret=text_file(root/"RG_SECRETS/rg_admin_token",4096)
parsed=urlsplit(url or "")
if not url or not secret or parsed.scheme not in ("https","http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme=="http" and parsed.hostname not in ("localhost","127.0.0.1")) or not re.fullmatch(r"[A-Za-z0-9_.~+/=-]{8,4096}",secret):
 print("ADMIN_CONFIG_UNAVAILABLE");raise SystemExit(1)
curl=shutil.which("curl")
if not curl:
 print("CURL_MISSING");raise SystemExit(1)
config='header = "Authorization: Bearer '+secret+'"\nconnect-timeout = 8\nmax-time = 20\n'
def get(path):
 try:
  r=subprocess.run([curl,"--silent","--show-error","--config","-","--max-filesize","12000000","--write-out","\nHTTP_CODE:%{http_code}",url.rstrip("/")+path],
   input=config.encode(),capture_output=True,timeout=25)
  marker=b"\nHTTP_CODE:"
  if r.returncode or marker not in r.stdout:return "ERROR",{}
  raw,code=r.stdout.rsplit(marker,1)
  return code.decode("ascii","replace").strip(),obj(json.loads(raw))
 except (OSError,ValueError,subprocess.TimeoutExpired):return "ERROR",{}
print("=== RG TELEGRAM V17 DELIVERY / MODERATION / ALERT AUDIT - READ ONLY ===")
print("KYIV_DATE",today)
state=Path("/volume1/docker/RG_NAS_STATE")
for key in ("last_deploy_status","scheduler_last_check_status","telegram_control_plane_status","telegram_watchdog_status","telegram_startup_selftest_status"):
 v=text_file(state/key,100)
 print("NAS",key,safe(v))
h,s=get("/status")
st=obj(s.get("state"))
scanner=obj(st.get("telegram-video-scanner-health-v3"))
textscan=obj(st.get("telegram-text-scanner-health-v1"))
if age(textscan.get("checkedAt"))=="UNKNOWN":
 textscan=obj(scanner.get("textPosts"))
moder=obj(st.get("telegram-video-moderation-health-v2"))
heartbeat=obj(st.get("air-alert-heartbeat-v1"))
alertq=obj(st.get("air-alert-queue-health-v1"))
minute=obj(st.get("minute-silence-state-v1"))
print("ADMIN_STATUS","http",h,"scanner_ok",truth(scanner.get("ok")),"scanner_age_sec",age(scanner.get("checkedAt")),
 "moderation_ok",truth(moder.get("ok")),"moderation_age_sec",age(moder.get("liveCheckedAt") or moder.get("checkedAt")))
print("TEXT_SCANNER","ok",truth(textscan.get("ok")),"age_sec",age(textscan.get("checkedAt")),
 "found_last_cycle",num(textscan.get("found") if textscan.get("found") is not None else textscan.get("discovered")),
 "queued_last_cycle",num(textscan.get("queued") if textscan.get("queued") is not None else textscan.get("candidatesQueued")),
 "errors_last_cycle",num(textscan.get("errors")))
daily=obj(scanner.get("dailyMetrics"))
print("SCANNER_TODAY","date_matched",truth(daily.get("dateKey")==today),
 "video_sent",num(daily.get("videoSent")) if daily.get("dateKey")==today else "UNKNOWN",
 "text_sent",num(daily.get("textSent")) if daily.get("dateKey")==today else "UNKNOWN",
 "candidates_queued",num(daily.get("candidatesQueued")) if daily.get("dateKey")==today else "UNKNOWN",
 "delivery_failures",num(daily.get("deliveryFailures")) if daily.get("dateKey")==today else "UNKNOWN")
print("MODERATION_POLL","fetched",num(moder.get("updatesFetched")),"processed",num(moder.get("updatesProcessed")),
 "failed",num(moder.get("updatesFailed")),"offset_blocked",truth(moder.get("offsetBlocked")),"degraded",truth(moder.get("degraded")))
qh,queues=get("/queues")
q=obj(queues.get("state"))
ph=obj(q.get("telegram-moderation-publish-health-v2"))
print("QUEUE_HEALTH","http",qh,
 "processing",count_queue(q.get("telegram-video-processing-queue-v2")),
 "publish",count_queue(q.get("telegram-moderation-publish-queue-v2")),
 "dead_letter",count_queue(q.get("telegram-video-dead-letter-v1")),
 "publish_health_age_sec",age(ph.get("checkedAt") or ph.get("lastRunAt") or ph.get("updatedAt")),
 "last_health_published",num(ph.get("published")),
 "last_health_failed",num(ph.get("failed")),"last_health_uncertain",num(ph.get("uncertain")))
dh,dbg=get("/moderation-debug?date="+today)
decisions=dbg.get("decisions") if isinstance(dbg.get("decisions"),list) else []
journal=obj(dbg.get("publicationJournal"))
rows=journal.get("items") if isinstance(journal.get("items"),list) else []
dec=collections.Counter(safe(x.get("decision")) for x in decisions if isinstance(x,dict))
publishedToday=[x for x in rows if isinstance(x,dict) and day(x.get("publishedAt"))==today]
confirmedToday=[x for x in publishedToday if x.get("messageId") is not None]
print("MODERATION_DEBUG","http",dh,"date_matched",truth(dbg.get("dateKey")==today),
 "recent_decisions",len(decisions),"decision_classes",json.dumps(dict(dec.most_common(10)),ensure_ascii=True),
 "journal_rows",len(rows),"journal_today",len(publishedToday),"journal_today_with_telegram_message_id",len(confirmedToday))
callbacks=obj(dbg.get("callbacks"))
print("CALLBACKS","summary_available",truth(bool(callbacks)),
 "events",num(callbacks.get("total") if "total" in callbacks else callbacks.get("processed")),
 "errors",num(callbacks.get("failed") if "failed" in callbacks else callbacks.get("errors")))
ch,candidates=get("/moderation-candidates?limit=250")
cards=candidates.get("items") if isinstance(candidates.get("items"),list) else []
groups=collections.Counter(safe(x.get("status")) for x in cards if isinstance(x,dict))
waiting=[x for x in cards if isinstance(x,dict) and x.get("status") in ("queued","pending")]
ready_cards=sum(1 for x in waiting if x.get("moderatorMessageId") is not None)
print("MODERATION_CANDIDATES","http",ch,"count",num(candidates.get("count")),"matched",num(candidates.get("matched")),
 "scanned",num(candidates.get("scanned")),"returned",len(cards),
 "statuses",json.dumps(dict(groups.most_common(10)),ensure_ascii=True),
 "waiting",len(waiting),"waiting_with_moderator_message_id",ready_cards)
print("KYIV_ALERT_HEARTBEAT","ok",truth(heartbeat.get("ok")),
 "last_successful_poll_age_sec",age(heartbeat.get("lastSuccessfulPollAt")),
 "last_checked_age_sec",age(heartbeat.get("checkedAt")),
 "consumer_error_present",truth(bool(alertq.get("lastConsumerError"))),
 "queue_health_checked_age_sec",age(alertq.get("checkedAt") or alertq.get("updatedAt")))
mh,machine=get("/alert-machine")
mb=obj(machine.get("body"))
print("KYIV_ALERT_MACHINE","http",mh,"service_ok",truth(machine.get("ok")),
 "initialized",truth(mb.get("initialized")),"active",truth(mb.get("active")),
 "last_observation_age_sec",age(mb.get("lastObservedAt")),
 "pending_transition",truth(bool(mb.get("pendingTransition"))),
 "public_transition_history_rows",len(mb.get("publicTransitions")) if isinstance(mb.get("publicTransitions"),list) else "UNKNOWN")
ldh,ledger=get("/alert-delivery?key=air-alert-delivered-v3:minute-silence:"+today)
le=obj(obj(ledger.get("body")).get("entry"))
print("MINUTE_SILENCE_TODAY","ledger_http",ldh,"ledger_service_ok",truth(ledger.get("ok")),
 "delivery_status",safe(le.get("status")),"telegram_message_id_present",truth(le.get("messageId") is not None),
 "delivered_age_sec",age(le.get("deliveredAt")),
 "state_date_matches",truth(minute.get("lastPublishedDate")==today),
 "state_message_id_present",truth(minute.get("messageId") is not None))
rp,production=get("/production-state")
print("PRODUCTION","http",rp,"ready",truth(production.get("ok")),
 "blocking_stage",safe(obj(production.get("productionReadiness")).get("blockingStage")))
print("AUDIT_SCOPE","DELIVERY_LOGS_ONLY_NO_MESSAGES_SENT")
print("RG_TELEGRAM_V17_COMPLETE_READ_ONLY")
PY
