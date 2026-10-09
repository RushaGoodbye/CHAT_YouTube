#!/bin/sh
# RG Telegram V21 - read-only forensic snapshot of the newest NAS deploy.
# Prints only allowlisted status labels and error categories, no raw log lines,
# secrets, URLs, message data, request bodies, or mutating operations.
set -eu
[ "$(id -u)" = "0" ] || { echo "sudo_required"; exit 2; }
python3 - <<'PY'
from pathlib import Path
import re,time,json
root=Path("/volume1/docker")
state=root/"RG_NAS_STATE"
now=time.time()
target="ee1f3ed8e7b567df37e3addda066c49a41996be3"
def read(key,cap=200):
 try:
  f=state/key
  if f.is_symlink() or not f.is_file() or f.stat().st_size>cap:return None
  return f.read_text(encoding="utf8",errors="replace").strip()
 except OSError:return None
def stat(key):
 try:return max(0,int(now-(state/key).stat().st_mtime))
 except OSError:return "UNKNOWN"
def render(v):
 return v if v and re.fullmatch(r"[A-Za-z0-9_.:-]{1,90}",v) else "UNKNOWN"
def b(v):return "TRUE" if v else "FALSE"
print("=== RG TELEGRAM V22 DEPLOY + R7 FROZEN CHECK / READ ONLY ===")
print("EXPECTED_SHA_PREFIX",target[:12])
for key in ("last_deploy_status","deploy_stage","deploy_sync_status",
            "scheduler_last_check_status","last_check_status","live_smoke_status",
            "telegram_watchdog_status","telegram_startup_selftest_status",
            "rg_telegram_control_release_status","rg_telegram_control_release_id"):
 print("STATE",key,render(read(key)),"age_sec",stat(key))
for key in ("last_video_deploy_status","last_alerts_deploy_status","last_content_deploy_status"):
 raw=read(key,150)
 print("WORKER_STATUS",key,
       ("OK" if raw=="OK" else "ERROR" if raw and raw.startswith("ERROR") else render(raw)),
       "age_sec",stat(key))
last_error=read("last_error",1024)
error_class="NONE"
if last_error:
 if "Frozen release" in last_error:error_class="FROZEN_RELEASE_REUSE"
 elif "Video Worker deploy failed" in last_error:error_class="VIDEO_DEPLOY_FAILED"
 elif "Alert Worker deploy failed" in last_error:error_class="ALERT_DEPLOY_FAILED"
 elif "Content Worker deploy failed" in last_error:error_class="CONTENT_DEPLOY_FAILED"
 elif "tar" in last_error.lower():error_class="EXTRACTION_FAILED"
 else:error_class="OTHER_REDACTED"
print("LAST_ERROR_CLASS",error_class,"age_sec",stat("last_error"))

for key in ("last_deployed_sha","last_synced_head_sha",
            "rg_telegram_control_release_source_sha"):
 sha=read(key,100)
 print("SHA",key,"matches_new_R7",b(sha==target),
       "prefix",(sha[:12] if sha and re.fullmatch("[a-f0-9]{40}",sha) else "UNKNOWN"))
log=state/"auto-deploy.log"
try:
 if log.is_symlink() or log.stat().st_size>50000000:raise ValueError()
 lines=log.read_text(encoding="utf8",errors="replace").splitlines()
 print("LOG_AGE_SEC",max(0,int(now-log.stat().st_mtime)),"lines",len(lines))
except (OSError,ValueError):
 print("LOG_NOT_READABLE");lines=[]
starts=[i for i,line in enumerate(lines) if re.search(r"Downloading RushaGoodbye/rasha-goodbye-news-bot@",line)]
print("DEPLOY_DOWNLOAD_CYCLES",len(starts))
for j,idx in enumerate(starts[-3:],1):
 end=starts[starts.index(idx)+1] if starts.index(idx)+1<len(starts) else len(lines)
 sub=lines[idx:end]
 print("=== CYCLE",j,"tail_lines",len(sub),"===")
 start_sha=re.search(r"Downloading RushaGoodbye/rasha-goodbye-news-bot@([a-f0-9]{40})",lines[idx])
 print("CYCLE_SHA","matches_R7",b(start_sha is not None and start_sha.group(1)==target),
       "prefix",start_sha.group(1)[:12] if start_sha else "UNKNOWN")
 for line in sub:
  if "Starting video deploy container" in line:
   print("EVENT","VIDEO_CONTAINER_STARTED")
  elif "video deploy container exited with code" in line:
   found=re.search(r"video deploy container exited with code ([0-9]+)",line)
   print("EVENT","VIDEO_CONTAINER_FAILED","exit_code",found.group(1) if found else "UNKNOWN")
  elif "video deploy timed out" in line:
   print("EVENT","VIDEO_CONTAINER_TIMEOUT")
  elif "Video Worker deploy failed" in line:
   print("EVENT","VIDEO_WORKER_DEPLOY_FAILED")
  elif "Starting alerts deploy container" in line:
   print("EVENT","ALERT_CONTAINER_STARTED")
  elif "Starting content deploy container" in line:
   print("EVENT","CONTENT_CONTAINER_STARTED")
  elif "RG_NAS_DEPLOY_OK " in line or "RG_NAS_CONTROL_PLANE_FAST_DEPLOY_OK " in line:
   print("EVENT","DEPLOY_OK")
  elif "RG Telegram Control STABLE contracts: OK" in line:
   print("EVENT","STABLE_CONTRACT_OK")
  elif "Frozen release" in line and "bump releaseId" in line:
   print("EVENT","FROZEN_RELEASE_ID_REUSE_REJECTED")
  elif "curl: (" in line:
   match=re.search(r"curl: \((\d+)\)",line)
   print("EVENT","CURL_FAILED","exit_code",match.group(1) if match else "UNKNOWN")
  elif "Error response from daemon" in line:
   print("EVENT","DOCKER_ERROR_REDACTED")
  elif re.search(r"Traceback \(most recent call last\)",line):
   print("EVENT","PYTHON_TRACEBACK")
  elif re.search(r"AssertionError:",line):
   print("EVENT","VALIDATOR_ASSERTION_REDACTED")
  elif "RG_NAS_" in line and "FAIL" in line:
   print("EVENT","DEPLOY_FAILURE_MARKER")
  elif re.search(r"(^|\s)ERROR:",line):
   x=line.split("ERROR:",1)[-1].strip()
   if "Frozen release" in x:print("EVENT","FROZEN_RELEASE_ID_REUSE_REJECTED")
   elif "Archive" in x:print("EVENT","ARCHIVE_ERROR_REDACTED")
   else:print("EVENT","OTHER_ERROR_REDACTED")
  elif "Container " in line and " Recreate" in line:
   print("EVENT","CONTAINER_RECREATE")
print("RG_TELEGRAM_V22_COMPLETE_READ_ONLY")
PY
