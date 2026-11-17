#!/bin/sh
# Single guarded upgrade of the ISOLATED Gatus monitor to ACTIVE RG NEWS2.
# NEVER starts Telegram polling, publishes channels, re-enables DSM tasks,
# restarts Cloudflare or alters YouTube/Auto Edit.
set -eu
PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PATH
umask 077
REF="$1"
if ! printf '%s' "$REF" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "INVALID_PINNED_REF" >&2
  exit 2
fi
[ "$(id -u)" -eq 0 ] || { echo "ROOT_REQUIRED" >&2; exit 2; }

ROOT=/volume1/docker
MON="$ROOT/RG_NAS_MONITOR"
NEWS="$ROOT/RG_TELEGRAM_NEWS_2"
TASK="$NEWS/rg_news_dsm_tick.sh"
BASE="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$REF/rg_remote_control/nas/monitoring"
for bin in curl docker python3; do
  command -v "$bin" >/dev/null 2>&1 || { echo "MISSING_TOOL=$bin" >&2; exit 2; }
done
[ -f "$MON/.rg_gatus_managed" ] || { echo "GATUS_NOT_MANAGED_REFUSE_UPDATE" >&2; exit 3; }
[ -f "$MON/compose.yaml" ] && [ -f "$MON/config.yaml" ] || { echo "GATUS_CONFIG_MISSING" >&2; exit 3; }
[ -f "$MON/.env" ] && [ -f "$MON/token" ] || { echo "GATUS_TOKEN_MISSING" >&2; exit 3; }
[ -f "$TASK" ] || { echo "ACTIVE_NEWS2_TICK_MISSING" >&2; exit 3; }
/bin/sh -n "$TASK" || { echo "NEWS2_TICK_SYNTAX_INVALID" >&2; exit 3; }
# Require the expected still-running, isolated service; never replace foreign containers.
[ "$(docker inspect -f '{{.State.Running}}' rg-nas-gatus 2>/dev/null || echo false)" = true ] || { echo "GATUS_NOT_RUNNING" >&2; exit 3; }
[ "$(docker inspect -f '{{.State.Running}}' rg-nas-gatus-observer 2>/dev/null || echo false)" = true ] || { echo "OBSERVER_NOT_RUNNING" >&2; exit 3; }
grep -Fq "127.0.0.1:18080:8080" "$MON/compose.yaml" || { echo "UNEXPECTED_GATUS_PORT_CONFIGURATION" >&2; exit 3; }
grep -Fq "rg-nas-gatus-observer" "$MON/compose.yaml" || { echo "UNEXPECTED_GATUS_CONTAINERS" >&2; exit 3; }
[ ! -e "$ROOT/RG_SECRETS/rg_nas_telegram_cutover_enabled" ] || { echo "CUTOVER_GATE_EXISTS_ABORT" >&2; exit 3; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STAGE="$(mktemp -d "$MON/.news2-upgrade.XXXXXX")"
BACKUP="$MON/backups/news2-upgrade-$STAMP"
DEPLOY_STARTED=0
COMMITTED=0
cleanup() {
  code="$?"
  if [ "$DEPLOY_STARTED" -eq 1 ] && [ "$COMMITTED" -eq 0 ]; then
    echo "GATUS_UPGRADE_FAILED_ROLLING_BACK_ISOLATED_MONITOR" >&2
    for f in compose.yaml config.yaml rg_nas_gatus_observer_v1.py; do
      if [ -f "$BACKUP/$f" ]; then cp -p "$BACKUP/$f" "$MON/$f"; fi
    done
    # v2 observer is separate; old compose refers to v1 observer.
    ( cd "$MON" && docker compose -p rg-nas-monitor -f compose.yaml up -d --force-recreate gatus observer ) >/dev/null 2>&1 || true
  fi
  rm -rf "$STAGE"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

curl -fsSL --connect-timeout 8 --max-time 35 "$BASE/rg_news2_batch_audit_v1.py" -o "$STAGE/rg_news2_batch_audit_v1.py"
curl -fsSL --connect-timeout 8 --max-time 35 "$BASE/rg_news2_gatus_observer_v2.py" -o "$STAGE/rg_news2_gatus_observer_v2.py"
curl -fsSL --connect-timeout 8 --max-time 35 "$BASE/compose-news2.yaml" -o "$STAGE/compose.yaml"
curl -fsSL --connect-timeout 8 --max-time 35 "$BASE/config-news2.yaml" -o "$STAGE/config.yaml"
for f in rg_news2_batch_audit_v1.py rg_news2_gatus_observer_v2.py compose.yaml config.yaml; do
  [ -s "$STAGE/$f" ] || { echo "EMPTY_SOURCE=$f" >&2; exit 4; }
done
echo "=== ACTIVE NEWS2 BATCH AUDIT ==="
python3 "$STAGE/rg_news2_batch_audit_v1.py" selftest
python3 "$STAGE/rg_news2_batch_audit_v1.py" diagnose
echo "=== NEWS2 TASK4 INSTALL GATE ==="
python3 "$STAGE/rg_news2_batch_audit_v1.py" diagnose | python3 -c '
import json,sys
d=json.load(sys.stdin)
task=d["news2_dsm_task"]
tick=d["news2_tick_script"]
if not d["task4_recent_execution_confirmed"]:
    raise SystemExit("TASK4_NOT_CONFIRMED: no change applied")
if not (task.get("enabled") and task.get("last_result")=="success" and tick.get("shell_syntax")=="PASS"
            and task.get("script_match")):
    raise SystemExit("TASK4_GATE_FAILED: no change applied")
callback=d["callback_state"]
if callback["count"] < 1:
    raise SystemExit("NEWS2_CALLBACK_SOURCE_NOT_FOUND: no monitoring change applied")
print("ACTIVE_NEWS2_TASK4_AND_CALLBACK_SOURCE_GATE=PASS")
'
# Validate Docker Compose with the pre-existing local token; no new credentials.
( cd "$STAGE" && docker compose --env-file "$MON/.env" -p rg-nas-monitor -f compose.yaml config -q )
mkdir -p "$MON/backups"
mkdir "$BACKUP"
for f in compose.yaml config.yaml rg_nas_gatus_observer_v1.py; do
  [ -f "$MON/$f" ] || { echo "REQUIRED_MONITOR_FILE_MISSING=$f" >&2; exit 4; }
  cp -p "$MON/$f" "$BACKUP/$f"
done
# Snapshot is complete. From here, any failure restores only Gatus files/containers.
DEPLOY_STARTED=1
cp -p "$STAGE/compose.yaml" "$MON/compose.yaml"
cp -p "$STAGE/config.yaml" "$MON/config.yaml"
cp -p "$STAGE/rg_news2_gatus_observer_v2.py" "$MON/rg_news2_gatus_observer_v2.py"
( cd "$MON" && docker compose -p rg-nas-monitor -f compose.yaml up -d --force-recreate gatus observer )
sleep 5
for c in rg-nas-gatus rg-nas-gatus-observer; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || echo false)" = true ] || {
    echo "MONITOR_CONTAINER_FAILED=$c" >&2
    exit 5
  }
done
curl -fsS --max-time 10 http://127.0.0.1:18080/ >/dev/null || { echo "GATUS_HTTP_FAILED" >&2; exit 5; }
# Force one isolated observer sample now (still no Telegram calls).
set +e
docker exec rg-nas-gatus-observer python3 -B /app/observer.py --root /nas --push \
  --token-file /run/monitor-token --url http://gatus:8080
RC="$?"
set -e
[ "$RC" -eq 0 ] || [ "$RC" -eq 2 ] || { echo "OBSERVER_PUSH_FAILED=$RC" >&2; exit 5; }
printf '%s\n' "$REF" > "$MON/.rg_news2_gatus_upgrade_ref"
COMMITTED=1
echo "RG_NEWS2_GATUS_UPGRADE=SUCCESS"
echo "GATUS_HTTP=200"
echo "NEW_CHECKS=news2-callback-state,news2-callback-log"
echo "BACKUP_CREATED=$BACKUP"
echo "LEGACY_SCHEDULER_NOT_REENABLED=yes"
echo "PUBLIC_CHANNEL_UNCHANGED=yes"
echo "SECOND_TELEGRAM_POLLER_STARTED=no"
