#!/bin/sh
# RG Telegram V10: media dead-letter + release-readiness verification. READ ONLY.
# Does not run bot, scheduler, deploy, watchdog, or change any queue or state file.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Requires sudo sh"; exit 2; }
python3 - <<'PY'
import collections,datetime,json,re,shutil,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit

R=Path("/volume1/docker"); S=R/"RG_NAS_STATE"
print("=== RG TELEGRAM V10 MEDIA + RELEASE DIAGNOSTIC READ-ONLY ===",flush=True)
now=time.time()
def read(p,limit=4096):
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return None
        return p.read_text(encoding="utf-8",errors="replace").strip()
    except OSError:return None
def parse_json(path,limit=300000):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:return {}
        d=json.loads(path.read_text(encoding="utf-8",errors="replace"))
        return d if isinstance(d,dict) else {}
    except (OSError,ValueError):return {}
def age(p):
    try:return max(0,int(now-p.stat().st_mtime))
    except OSError:return "UNKNOWN"
def ok(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def st(v):
    allowed={"OK","ERROR","RUNNING","PREPARE","VIDEO","ALERTS","CONTENT","LIVE_SMOKE","CONTROL_PLANE","RG_TELEGRAM_CONTROL_APP","COMPLETE","SYNCED","DEPLOYING","DEGRADED","FROZEN","ACTIVATED"}
    return v if v in allowed else "MISSING_OR_OTHER"
def count(v):
    if isinstance(v,list):return len(v)
    if isinstance(v,dict):
        if isinstance(v.get("items"),list):return len(v["items"])
        if isinstance(v.get("keys"),list):return len(v["keys"])
        for name in ("queued","count","size","length","remaining"):
            n=v.get(name)
            if type(n)==int and 0<=n<=100000:return n
    return 0
def iso_seconds(value):
    if not isinstance(value,str):return None
    try:
        d=datetime.datetime.fromisoformat(value.replace("Z","+00:00"))
        if d.tzinfo is None:return None
        return d.timestamp()
    except ValueError:return None
def classify_reason(v):
    if not isinstance(v,str):return "unspecified"
    if re.search(r"429|quota|rate.?limit|resource_exhausted",v,re.I):return "rate_or_quota"
    if re.search(r"timeout|timed out|5[0-9][0-9]|connection|fetch failed|network|temporar|unavailable",v,re.I):return "temporary_transport"
    if re.search(r"media|photo|video|watermark|file_id|image",v,re.I):return "media_related"
    if re.search(r"retry.exhaust|attempt",v,re.I):return "retry_exhausted"
    if re.search(r"denied|blocked|forbidden|unsupported|policy",v,re.I):return "policy_or_access"
    return "other"
print("NAS_STATUS")
for k in ("last_deploy_status","deploy_stage","deploy_sync_status","live_smoke_status","scheduler_last_check_status","telegram_startup_selftest_status","telegram_control_plane_status","telegram_watchdog_status"):
    p=S/k
    print(k,st(read(p,150)),"age_sec",age(p))
watch=parse_json(S/"telegram-watchdog-status.json",500000)
print("WATCHDOG","report_age_sec",age(S/"telegram-watchdog-status.json"),
      "ok",ok(watch.get("ok")),"issues_count",len(watch.get("issues") or []) if isinstance(watch.get("issues"),list) else "UNKNOWN")
if isinstance(watch.get("issues"),list):
    for name in watch["issues"][:15]:
        if isinstance(name,str) and re.fullmatch("[a-z][a-z0-9_:-]{0,90}",name):
            print("WATCHDOG_ISSUE",name)
print("RELEASE_ARTIFACTS")
root=R/"RG_RELEASES/telegram-control"
for key,p in [
    ("active_manifest",root/"current-release-manifest.json"),
    ("active_source",root/"current-release-source.json"),
    ("manifest_state",S/"rg_telegram_control_release_manifest.json"),
    ("release_source_sha",S/"rg_telegram_control_release_source_sha"),
    ("release_source_sha256",S/"rg_telegram_control_release_source_sha256")]:
    print("ARTIFACT",key,"exists",ok(p.is_file() and not p.is_symlink() and p.stat().st_size>0 if p.exists() else False),"age_sec",age(p))
manifest=parse_json(root/"current-release-manifest.json")
source=parse_json(root/"current-release-source.json")
print("RELEASE_META","source_active",ok(source.get("active")),
      "ids_match",ok(bool(manifest.get("releaseId")) and manifest.get("releaseId")==source.get("releaseId")),
      "sha_matches_state",ok(bool(source.get("sourceSha")) and source.get("sourceSha")==read(S/"rg_telegram_control_release_source_sha",100)),
      "source_of_truth_nas",ok(manifest.get("sourceOfTruth")=="nas" and source.get("nasIsReleaseSourceOfTruth") is True))
rid=source.get("releaseId")
if isinstance(rid,str) and re.fullmatch("[A-Za-z0-9_.-]{4,80}",rid):
    arch=source.get("sourceArchive")
    p=root/rid/arch if isinstance(arch,str) and re.fullmatch("RG_Telegram_Control_Source_[a-f0-9]{40}[.]tar[.]gz",arch) else None
    if p:
        print("SOURCE_ARCHIVE","present",ok(p.is_file() and not p.is_symlink()),"bytes",p.stat().st_size if p.is_file() else "UNKNOWN")
try:
    pending=list(root.glob(".current-release-manifest.json.*")) if root.is_dir() else []
    print("STAGED_RELEASE_MANIFEST_COUNT",len(pending))
except OSError:pass
print("=== LIVE READINESS AND MEDIA DEAD LETTER ===")
url=read(R/"RG_NAS_CONTROL/admin_url",1024)
secret=read(R/"RG_SECRETS/rg_admin_token",4096)
u=urlsplit(url or "")
if not url or not secret or u.scheme not in ("https","http") or not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme=="http" and u.hostname not in ("localhost","127.0.0.1")) or not re.fullmatch("[A-Za-z0-9_.~+/=-]{8,4096}",secret):
    print("ADMIN_CONFIG_UNAVAILABLE");raise SystemExit(1)
curl=shutil.which("curl")
if not curl:print("CURL_NOT_FOUND");raise SystemExit(1)
cfg='header = "Authorization: Bearer '+secret+'"\nconnect-timeout = 8\nmax-time = 26\n'
def fetch(path):
    try:
        p=subprocess.run([curl,"--silent","--show-error","--config","-","--max-filesize","10000000",
          "--write-out","\nRG_HTTP_CODE:%{http_code}",url.rstrip("/")+path],
          input=cfg.encode(),capture_output=True,timeout=31)
        mark=b"\nRG_HTTP_CODE:"
        if mark not in p.stdout:return "UNKNOWN",{}
        raw,code=p.stdout.rsplit(mark,1)
        code=code.decode("ascii","replace").strip()
        try:body=json.loads(raw)
        except (ValueError,UnicodeError):body={}
        return code if re.fullmatch("[0-9]{3}",code) else "UNKNOWN",body if isinstance(body,dict) else {}
    except (OSError,subprocess.TimeoutExpired):return "UNKNOWN",{}
code,prod=fetch("/production-state")
pr=prod.get("productionReadiness") or {}
pr=pr if isinstance(pr,dict) else {}
print("PRODUCTION","HTTP",code,"ok",ok(prod.get("ok")),"blocker",pr.get("blockingStage") if pr.get("blockingStage") in ("media","nas","publish","scanner","moderation","receipt","schedule","alerts") else "UNKNOWN")
for stage in (pr.get("stages") or [])[:12]:
    if not isinstance(stage,dict):continue
    ident=stage.get("id")
    if ident not in ("media","nas","publish","scanner","moderation","receipt","schedule","alerts"):continue
    detail=stage.get("detail")
    detail=detail if isinstance(detail,str) and re.fullmatch(r"[A-Za-z0-9_:=.,-]{1,110}",detail) else "REDACTED"
    print("STAGE",ident,"ok",ok(stage.get("ok")),"detail",detail)
queues=prod.get("queues") if isinstance(prod.get("queues"),dict) else {}
dead=queues.get("telegram-video-dead-letter-v1")
if not isinstance(dead,(dict,list)):
    code2,result=fetch("/queues")
    print("QUEUES_FALLBACK_HTTP",code2)
    queues=result.get("state") if isinstance(result.get("state"),dict) else {}
    dead=queues.get("telegram-video-dead-letter-v1")
print("DEAD_LETTER","present",ok(isinstance(dead,(dict,list))),"count",count(dead))
items=dead.get("items") if isinstance(dead,dict) else dead if isinstance(dead,list) else []
buckets=collections.Counter()
ages=collections.Counter()
recoverable=0
due=0
for record in items:
    if not isinstance(record,dict):continue
    buckets[classify_reason(record.get("reason"))]+=1
    at=iso_seconds(record.get("at"))
    if at is None:ages["unknown"]+=1
    elif now-at<24*3600:ages["less_1d"]+=1
    elif now-at<7*24*3600:ages["1_to_7d"]+=1
    else:ages["more_7d"]+=1
    transient=buckets is not None and classify_reason(record.get("reason")) in ("rate_or_quota","temporary_transport")
    if transient and isinstance(record.get("sourceUrl"),str) and re.match(r"^https?://t[.]me/[a-zA-Z0-9_]+/[0-9]+",record["sourceUrl"]):
        recoverable+=1
        next_at=iso_seconds(record.get("recoveryNextAttemptAt"))
        if next_at is None or next_at<=now:due+=1
print("DEAD_LETTER_REASON_GROUPS",json.dumps(dict(sorted(buckets.items())),sort_keys=True))
print("DEAD_LETTER_AGE_GROUPS",json.dumps(dict(sorted(ages.items())),sort_keys=True))
print("DEAD_LETTER_TRANSIENT_POSSIBLE",recoverable,"DUE_FOR_RETRY",due)
if isinstance(dead,dict):
    recovery=dead.get("recovery") if isinstance(dead.get("recovery"),dict) else {}
    for key in ("eligible","recovered","failed"):
        n=recovery.get(key)
        print("LAST_RECOVERY",key,n if type(n)==int and 0<=n<=10000 else "UNKNOWN")
print("RG_TELEGRAM_V10_COMPLETE_READ_ONLY")
PY
