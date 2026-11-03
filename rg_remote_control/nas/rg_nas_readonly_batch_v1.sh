#!/bin/sh
# One-session read-only NAS/DSM scheduler diagnostic; NEVER run task scripts.
set -eu
PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PATH
ROOT="/volume1/docker"
PRE="/tmp/rg_nas_scheduler_preflight_v1.py"
TASK="/tmp/rg_nas_synology_task_audit_v1.py"
REPO="RushaGoodbye/CHAT_YouTube"
REF="$1"
if ! printf '%s' "$REF" | grep -Eq '^[0-9a-f]{40}$'; then
  printf '%s\n' 'INVALID_PINNED_REF' >&2
  exit 2
fi
for entry in "rg_nas_scheduler_preflight_v1.py" "rg_nas_synology_task_audit_v1.py"; do
  curl --fail --silent --show-error --location --connect-timeout 8 --max-time 35 \
    "https://raw.githubusercontent.com/$REPO/$REF/rg_remote_control/nas/$entry" \
    -o "/tmp/$entry"
  if [ ! -s "/tmp/$entry" ]; then
    printf '%s\n' 'SOURCE_MISSING' >&2
    exit 2
  fi
done
printf '%s\n' '=== BATCH_SELFTEST ==='
/usr/bin/python3 "$PRE" selftest
/usr/bin/python3 "$TASK" selftest
printf '%s\n' '=== LATEST_HEARTBEATS_AND_PATHS ==='
/usr/bin/python3 "$PRE" diagnose
printf '%s\n' '=== SYNOLOGY_DSM_TASKS_AND_CRON ==='
/usr/bin/python3 "$TASK" diagnose
printf '%s\n' '=== READ_ONLY_SCRIPT_SYNTAX ==='
for name in RG_NAS_SCHEDULER_TICK.sh RG_NAS_MCP_TICK.sh RG_NAS_MCP_GUARD.sh; do
  if [ ! -f "$ROOT/$name" ]; then
    printf '%s=MISSING\n' "$name"
  elif /bin/sh -n "$ROOT/$name" >/dev/null 2>&1; then
    printf '%s=SYNTAX_PASS\n' "$name"
  else
    printf '%s=SYNTAX_ERROR\n' "$name"
  fi
done
printf '%s\n' '=== READ_ONLY_DOCKER_MONITOR ==='
if command -v docker >/dev/null 2>&1; then
  docker ps --filter name=rg-nas-gatus --format '{{.Names}} {{.Status}}' 2>/dev/null || printf '%s\n' 'DOCKER_QUERY_UNAVAILABLE'
else
  printf '%s\n' 'DOCKER_PATH_UNAVAILABLE'
fi
printf '%s\n' '=== BATCH_COMPLETE_READ_ONLY ==='
