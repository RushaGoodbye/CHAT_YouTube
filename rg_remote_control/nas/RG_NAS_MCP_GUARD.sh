#!/bin/sh
set -eu

ROOT="/volume1/docker"
STATE="$ROOT/RG_NAS_STATE"
GOLDEN="$ROOT/RG_NAS_GOLDEN"
MCP_SOURCE="$ROOT/RG_NAS_MCP/SOURCE"
LOG="$STATE/rg-resilience.log"
STATUS="$STATE/RG_CONTROL_CENTER.json"

mkdir -p "$STATE" "$GOLDEN"
NOW="$(date -Iseconds 2>/dev/null || date)"
printf '%s\n' "$NOW" > "$STATE/rg_resilience_heartbeat_at"

log() {
  printf '%s %s\n' "$NOW" "$*" >> "$LOG"
}

repair_file() {
  NAME="$1"
  MARKER="$2"
  LIVE="$ROOT/$NAME"
  KNOWN="$GOLDEN/$NAME"

  if [ ! -s "$KNOWN" ]; then
    return 0
  fi

  if [ ! -s "$LIVE" ] || ! grep -F "$MARKER" "$LIVE" >/dev/null 2>&1; then
    cp -f "$KNOWN" "$LIVE"
    log "RESTORED $NAME"
  fi
}

repair_file "RG_NAS_MCP_TICK.sh" "AUTO_EDIT_CALL_ROOT"
repair_file "RG_NAS_MCP_AUTO_EDIT_CALL.py" "auto_edit_"
repair_file "RG_NAS_MCP_YOUTUBE_CALL.py" "youtube_"
repair_file "RG_NAS_MCP_TELEGRAM_CALL.py" "telegram_"

NEED_STACK=0
for C in rg-nas-mcp-hub rg-mcp-youtube rg-mcp-telegram rg-mcp-auto-edit; do
  if ! docker inspect "$C" >/dev/null 2>&1; then
    NEED_STACK=1
    log "MISSING_CONTAINER $C"
    continue
  fi
  RUNNING="$(docker inspect -f '{{.State.Running}}' "$C" 2>/dev/null || printf false)"
  if [ "$RUNNING" != "true" ]; then
    NEED_STACK=1
    log "STOPPED_CONTAINER $C"
    continue
  fi
  HEALTH="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$C" 2>/dev/null || printf unknown)"
  if [ "$HEALTH" = "unhealthy" ]; then
    NEED_STACK=1
    log "UNHEALTHY_CONTAINER $C"
  fi
done

REPAIR_RESULT="not_needed"
if [ "$NEED_STACK" -eq 1 ] && [ -f "$MCP_SOURCE/docker-compose.yml" ]; then
  AUTO_ROOT=""
  if [ -f "$STATE/mcp_auto_edit_host_root" ]; then
    AUTO_ROOT="$(cat "$STATE/mcp_auto_edit_host_root" 2>/dev/null || true)"
  fi
  if [ -z "$AUTO_ROOT" ]; then
    for CANDIDATE in /volume1/RG_AUTO_EDIT /volume2/RG_AUTO_EDIT /volume3/RG_AUTO_EDIT /volume4/RG_AUTO_EDIT /volume5/RG_AUTO_EDIT /volume6/RG_AUTO_EDIT /volume7/RG_AUTO_EDIT /volume8/RG_AUTO_EDIT; do
      if [ -d "$CANDIDATE/YOUTUBE_CONTROL" ]; then
        AUTO_ROOT="$CANDIDATE"
        printf '%s\n' "$AUTO_ROOT" > "$STATE/mcp_auto_edit_host_root"
        break
      fi
    done
  fi

  if [ -n "$AUTO_ROOT" ]; then
    if docker compose version >/dev/null 2>&1; then
      if RG_AUTO_EDIT_HOST_ROOT="$AUTO_ROOT" docker compose -p rg-nas-mcp -f "$MCP_SOURCE/docker-compose.yml" up -d >> "$LOG" 2>&1; then
        REPAIR_RESULT="ok"
      else
        REPAIR_RESULT="error"
      fi
    elif command -v docker-compose >/dev/null 2>&1; then
      if RG_AUTO_EDIT_HOST_ROOT="$AUTO_ROOT" docker-compose -p rg-nas-mcp -f "$MCP_SOURCE/docker-compose.yml" up -d >> "$LOG" 2>&1; then
        REPAIR_RESULT="ok"
      else
        REPAIR_RESULT="error"
      fi
    else
      REPAIR_RESULT="compose_missing"
    fi
  else
    REPAIR_RESULT="auto_root_missing"
  fi
fi

HUB="missing"
AUTO="missing"
YT="missing"
TG="missing"
docker inspect rg-nas-mcp-hub >/dev/null 2>&1 && HUB="$(docker inspect -f '{{.State.Status}}' rg-nas-mcp-hub 2>/dev/null || printf unknown)"
docker inspect rg-mcp-auto-edit >/dev/null 2>&1 && AUTO="$(docker inspect -f '{{.State.Status}}' rg-mcp-auto-edit 2>/dev/null || printf unknown)"
docker inspect rg-mcp-youtube >/dev/null 2>&1 && YT="$(docker inspect -f '{{.State.Status}}' rg-mcp-youtube 2>/dev/null || printf unknown)"
docker inspect rg-mcp-telegram >/dev/null 2>&1 && TG="$(docker inspect -f '{{.State.Status}}' rg-mcp-telegram 2>/dev/null || printf unknown)"

OVERALL="ok"
if [ "$HUB" != "running" ] || [ "$AUTO" != "running" ] || [ "$YT" != "running" ] || [ "$TG" != "running" ] || [ "$REPAIR_RESULT" = "error" ]; then
  OVERALL="degraded"
fi

cat > "$STATUS.tmp" <<EOF
{
  "schema": "RG_CONTROL_CENTER_V1",
  "updated_at": "$NOW",
  "status": "$OVERALL",
  "hub": "$HUB",
  "auto_edit": "$AUTO",
  "youtube": "$YT",
  "telegram": "$TG",
  "repair": "$REPAIR_RESULT",
  "github_fallback": "enabled",
  "credentials": "isolated"
}
EOF
mv -f "$STATUS.tmp" "$STATUS"
