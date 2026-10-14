#!/bin/sh
# RG Telegram News2 MCP cutover: explicit preflight, opt-in apply, targeted rollback.
set -eu
DOCKER=/usr/local/bin/docker
BRANCH=telegram-nas-news2-bridge-20261014
REPO=https://github.com/RushaGoodbye/CHAT_YouTube.git
STAGE=/volume1/docker/RG_NAS_MCP_NEWS2_STAGE
BASE=/volume1/docker/RG_NAS_MCP
WORK=$STAGE/rg_remote_mcp
MODE=${1:-preflight}
test -x "$DOCKER" || { echo "STOP: Docker binary missing"; exit 20; }
"$DOCKER" compose version >/dev/null || { echo "STOP: Docker compose plugin missing"; exit 21; }
test -d /volume1/docker/RG_TELEGRAM_NEWS_2 || { echo "STOP: News2 missing"; exit 22; }
test -d "$BASE/rg_remote_mcp" || { echo "STOP: expected existing MCP source layout not verified"; exit 23; }
ORIGINAL=$BASE/rg_remote_mcp
cd "$ORIGINAL"
"$DOCKER" compose -p rg-nas-mcp config >/dev/null || { echo "STOP: original Compose invalid"; exit 24; }
case "$MODE" in
preflight)
  echo "PREFLIGHT_OK: original Compose available; News2 directory exists"
  echo "Only telegram-worker and hub are eligible for targeted deployment"
  ;;
apply)
  test "${RG_EXPLICIT_APPLY:-}" = "YES" || { echo "STOP: set RG_EXPLICIT_APPLY=YES"; exit 25; }
  mkdir -p "$STAGE"
  if test ! -d "$STAGE/.git"; then
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$STAGE"
  else
    git -C "$STAGE" fetch --depth 1 origin "$BRANCH"
    git -C "$STAGE" checkout -f FETCH_HEAD
  fi
  test -f "$WORK/docker-compose.yml" || { echo "STOP: staged compose missing"; exit 26; }
  cd "$WORK"
  "$DOCKER" compose -p rg-nas-mcp config >/dev/null
  # Builds images without touching the production containers.
  "$DOCKER" compose -p rg-nas-mcp build hub telegram-worker
  # Apply targeted services only; never recreate YouTube or Auto Edit worker.
  if ! "$DOCKER" compose -p rg-nas-mcp up -d --no-deps hub telegram-worker; then
    cd "$ORIGINAL"
    "$DOCKER" compose -p rg-nas-mcp up -d --no-deps hub telegram-worker
    echo "APPLY_FAILED: attempted rollback to original Compose"
    exit 27
  fi
  sleep 5
  if ! "$DOCKER" inspect -f '{{.State.Health.Status}}' rg-mcp-telegram | grep -qx healthy; then
    cd "$ORIGINAL"
    "$DOCKER" compose -p rg-nas-mcp up -d --no-deps --build hub telegram-worker
    echo "HEALTH_FAILED: rolled back to original Compose"
    exit 28
  fi
  echo "APPLY_SUCCESS: telegram MCP container healthy; no Telegram delivery claim"
  ;;
rollback)
  cd "$ORIGINAL"
  "$DOCKER" compose -p rg-nas-mcp up -d --no-deps --build hub telegram-worker
  echo "ROLLBACK_REQUESTED: original hub and telegram worker restored"
  ;;
*)
  echo "Usage: $0 preflight|apply|rollback"
  exit 2
  ;;
esac
