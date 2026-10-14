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
# Discover the *actual* Compose working directory from existing container labels.
ORIGINAL=$("$DOCKER" inspect rg-mcp-telegram --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)
PROJECT=$("$DOCKER" inspect rg-mcp-telegram --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || true)
CONFIG_FILES=$("$DOCKER" inspect rg-mcp-telegram --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' 2>/dev/null || true)
printf 'MCP_DISCOVERY project=%s working_dir=%s config_files=%s\n' "$PROJECT" "$ORIGINAL" "$CONFIG_FILES"
test -n "$PROJECT" && test "$PROJECT" != "<no value>" || { echo "STOP: Compose project label missing"; exit 23; }
test -n "$ORIGINAL" && test "$ORIGINAL" != "<no value>" && test -d "$ORIGINAL" || { echo "STOP: actual Compose working directory not found"; exit 23; }
test -n "$CONFIG_FILES" && test "$CONFIG_FILES" != "<no value>" || { echo "STOP: original Compose config label missing"; exit 23; }
case "$CONFIG_FILES" in *,*) echo "STOP: multiple Compose files require explicit support"; exit 23;; esac
test -f "$CONFIG_FILES" || { echo "STOP: original Compose file not found"; exit 23; }
cd "$ORIGINAL"
"$DOCKER" compose -f "$CONFIG_FILES" -p "$PROJECT" config >/dev/null || { echo "STOP: original Compose invalid"; exit 24; }
case "$MODE" in
preflight)
  echo "PREFLIGHT_OK: original Compose available; News2 directory exists"
  echo "Only telegram-worker and hub are eligible for targeted deployment"
  ;;
apply)
  test "${RG_EXPLICIT_APPLY:-}" = "YES" || { echo "STOP: set RG_EXPLICIT_APPLY=YES"; exit 25; }
  command -v git >/dev/null 2>&1 || { echo "STOP: git missing on NAS"; exit 29; }
  mkdir -p "$STAGE"
  if test ! -d "$STAGE/.git"; then
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$STAGE"
  else
    git -C "$STAGE" fetch --depth 1 origin "$BRANCH"
    git -C "$STAGE" checkout -f FETCH_HEAD
  fi
  test -f "$WORK/docker-compose.yml" || { echo "STOP: staged compose missing"; exit 26; }
  cd "$WORK"
  "$DOCKER" compose -p "$PROJECT" config >/dev/null
  # Pin the reviewed branch state before any build; log the exact commit.
  git -C "$STAGE" rev-parse HEAD
  # Builds images without touching the production containers.
  "$DOCKER" compose -p "$PROJECT" build hub telegram-worker
  # Apply targeted services only; never recreate YouTube or Auto Edit worker.
  if ! "$DOCKER" compose -p "$PROJECT" up -d --no-deps hub telegram-worker; then
    cd "$ORIGINAL"
    "$DOCKER" compose -f "$CONFIG_FILES" -p "$PROJECT" up -d --no-deps --build hub telegram-worker
    echo "APPLY_FAILED: attempted rollback to original Compose"
    exit 27
  fi
  HEALTHY=NO
  ATTEMPT=0
  while test "$ATTEMPT" -lt 12; do
    if "$DOCKER" inspect -f '{{.State.Health.Status}}' rg-mcp-telegram | grep -qx healthy; then HEALTHY=YES; break; fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 5
  done
  if test "$HEALTHY" != YES; then
    cd "$ORIGINAL"
    "$DOCKER" compose -f "$CONFIG_FILES" -p "$PROJECT" up -d --no-deps --build hub telegram-worker
    echo "HEALTH_FAILED: rolled back to original Compose"
    exit 28
  fi
  echo "APPLY_SUCCESS: telegram MCP container healthy; no Telegram delivery claim"
  ;;
rollback)
  cd "$ORIGINAL"
  "$DOCKER" compose -f "$CONFIG_FILES" -p "$PROJECT" up -d --no-deps --build hub telegram-worker
  echo "ROLLBACK_REQUESTED: original hub and telegram worker restored"
  ;;
*)
  echo "Usage: $0 preflight|apply|rollback"
  exit 2
  ;;
esac
