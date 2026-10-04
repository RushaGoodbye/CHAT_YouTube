#!/bin/sh
set -eu

ROOT="/volume1/docker"
STATE="$ROOT/RG_NAS_STATE"
MCP_ROOT="$ROOT/RG_NAS_MCP"
MCP_DIR="$MCP_ROOT/SOURCE"
DEPLOY_REQUEST="$MCP_ROOT/DEPLOY_REQUEST"
SMOKE_REQUEST="$MCP_ROOT/SMOKE_REQUEST"
DEPLOY_STATUS="$STATE/mcp_deploy_status"
DEPLOY_LOG="$STATE/mcp-deploy.log"
SMOKE_STATUS="$STATE/mcp_smoke_status"
SMOKE_LOG="$STATE/mcp-smoke.log"
AUTO_ROOT_FILE="$STATE/mcp_auto_edit_host_root"

mkdir -p "$STATE" "$MCP_ROOT"

detect_auto_root() {
  if [ -f "$AUTO_ROOT_FILE" ]; then
    CACHED="$(cat "$AUTO_ROOT_FILE" 2>/dev/null || true)"
    if [ -n "$CACHED" ] && docker run --rm       --mount "type=bind,src=$CACHED,dst=/probe,readonly"       node:22-bookworm-slim       sh -c 'test -d /probe/YOUTUBE_CONTROL' >/dev/null 2>&1
    then
      printf '%s\n' "$CACHED"
      return 0
    fi
  fi

  for CANDIDATE in     /volume1/RG_AUTO_EDIT     /volume2/RG_AUTO_EDIT     /volume3/RG_AUTO_EDIT     /volume4/RG_AUTO_EDIT     /volume5/RG_AUTO_EDIT     /volume6/RG_AUTO_EDIT     /volume7/RG_AUTO_EDIT     /volume8/RG_AUTO_EDIT
  do
    if docker run --rm       --mount "type=bind,src=$CANDIDATE,dst=/probe,readonly"       node:22-bookworm-slim       sh -c 'test -d /probe/YOUTUBE_CONTROL' >/dev/null 2>&1
    then
      printf '%s\n' "$CANDIDATE" > "$AUTO_ROOT_FILE"
      printf '%s\n' "$CANDIDATE"
      return 0
    fi
  done
  return 1
}

if [ -f "$DEPLOY_REQUEST" ]; then
  printf '%s\n' "RUNNING" > "$DEPLOY_STATUS"
  : > "$DEPLOY_LOG"

  if [ ! -f "$MCP_DIR/docker-compose.yml" ]; then
    printf '%s\n' "Missing $MCP_DIR/docker-compose.yml" >> "$DEPLOY_LOG"
    printf '%s\n' "ERROR" > "$DEPLOY_STATUS"
  elif ! AUTO_ROOT="$(detect_auto_root)"; then
    printf '%s\n' "RG_AUTO_EDIT host root was not found on /volume1..8" >> "$DEPLOY_LOG"
    printf '%s\n' "ERROR" > "$DEPLOY_STATUS"
  else
    printf 'RG_AUTO_EDIT_HOST_ROOT=%s\n' "$AUTO_ROOT" >> "$DEPLOY_LOG"
    if docker compose version >/dev/null 2>&1; then
      if RG_AUTO_EDIT_HOST_ROOT="$AUTO_ROOT" docker compose         -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml"         up -d --build >> "$DEPLOY_LOG" 2>&1
      then
        RG_AUTO_EDIT_HOST_ROOT="$AUTO_ROOT" docker compose           -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml"           ps >> "$DEPLOY_LOG" 2>&1 || true
        printf '%s\n' "OK" > "$DEPLOY_STATUS"
      else
        printf '%s\n' "ERROR" > "$DEPLOY_STATUS"
      fi
    elif command -v docker-compose >/dev/null 2>&1; then
      if RG_AUTO_EDIT_HOST_ROOT="$AUTO_ROOT" docker-compose         -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml"         up -d --build >> "$DEPLOY_LOG" 2>&1
      then
        RG_AUTO_EDIT_HOST_ROOT="$AUTO_ROOT" docker-compose           -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml"           ps >> "$DEPLOY_LOG" 2>&1 || true
        printf '%s\n' "OK" > "$DEPLOY_STATUS"
      else
        printf '%s\n' "ERROR" > "$DEPLOY_STATUS"
      fi
    else
      printf '%s\n' "Docker Compose unavailable" >> "$DEPLOY_LOG"
      printf '%s\n' "ERROR" > "$DEPLOY_STATUS"
    fi
  fi
  rm -f "$DEPLOY_REQUEST" 2>/dev/null || true
fi

if [ -f "$SMOKE_REQUEST" ]; then
  printf '%s\n' "RUNNING" > "$SMOKE_STATUS"
  if docker inspect rg-nas-mcp-hub >/dev/null 2>&1; then
    if docker exec rg-nas-mcp-hub python -m rg_remote_mcp.smoke       > "$SMOKE_LOG" 2>&1
    then
      printf '%s\n' "OK" > "$SMOKE_STATUS"
    else
      printf '%s\n' "ERROR" > "$SMOKE_STATUS"
    fi
  else
    printf '%s\n' "rg-nas-mcp-hub missing" > "$SMOKE_LOG"
    printf '%s\n' "ERROR" > "$SMOKE_STATUS"
  fi
  rm -f "$SMOKE_REQUEST" 2>/dev/null || true
fi


YOUTUBE_CALL_ROOT="$MCP_ROOT/YOUTUBE_CALLS"
YOUTUBE_CALL_REQUESTS="$YOUTUBE_CALL_ROOT/requests"
YOUTUBE_CALL_RESULTS="$YOUTUBE_CALL_ROOT/results"
YOUTUBE_CALL_ERRORS="$YOUTUBE_CALL_ROOT/errors"
YOUTUBE_CALL_HELPER="$ROOT/RG_NAS_MCP_YOUTUBE_CALL.py"

mkdir -p "$YOUTUBE_CALL_REQUESTS" "$YOUTUBE_CALL_RESULTS" "$YOUTUBE_CALL_ERRORS"

if [ -f "$YOUTUBE_CALL_HELPER" ] && docker inspect rg-nas-mcp-hub >/dev/null 2>&1; then
  for REQ in "$YOUTUBE_CALL_REQUESTS"/*.json; do
    [ -e "$REQ" ] || break
    BASE="$(basename "$REQ" .json)"
    RESULT="$YOUTUBE_CALL_RESULTS/$BASE.json"
    ERROR="$YOUTUBE_CALL_ERRORS/$BASE.log"
    TMP_RESULT="$YOUTUBE_CALL_RESULTS/$BASE.tmp"

    if docker cp "$YOUTUBE_CALL_HELPER" rg-nas-mcp-hub:/tmp/rg_youtube_call.py >/dev/null 2>&1 \
      && docker cp "$REQ" rg-nas-mcp-hub:/tmp/rg_youtube_request.json >/dev/null 2>&1 \
      && docker exec rg-nas-mcp-hub python /tmp/rg_youtube_call.py /tmp/rg_youtube_request.json > "$TMP_RESULT" 2> "$ERROR"
    then
      mv -f "$TMP_RESULT" "$RESULT"
      rm -f "$ERROR" 2>/dev/null || true
    else
      rm -f "$TMP_RESULT" 2>/dev/null || true
    fi

    rm -f "$REQ" 2>/dev/null || true
    docker exec rg-nas-mcp-hub rm -f /tmp/rg_youtube_call.py /tmp/rg_youtube_request.json >/dev/null 2>&1 || true
  done
fi


AUTO_EDIT_CALL_ROOT="$MCP_ROOT/AUTO_EDIT_CALLS"
AUTO_EDIT_CALL_REQUESTS="$AUTO_EDIT_CALL_ROOT/requests"
AUTO_EDIT_CALL_RESULTS="$AUTO_EDIT_CALL_ROOT/results"
AUTO_EDIT_CALL_ERRORS="$AUTO_EDIT_CALL_ROOT/errors"
AUTO_EDIT_CALL_HELPER="$ROOT/RG_NAS_MCP_AUTO_EDIT_CALL.py"

mkdir -p "$AUTO_EDIT_CALL_REQUESTS" "$AUTO_EDIT_CALL_RESULTS" "$AUTO_EDIT_CALL_ERRORS"

if [ -f "$AUTO_EDIT_CALL_HELPER" ] && docker inspect rg-nas-mcp-hub >/dev/null 2>&1; then
  for REQ in "$AUTO_EDIT_CALL_REQUESTS"/*.json; do
    [ -e "$REQ" ] || break
    BASE="$(basename "$REQ" .json)"
    RESULT="$AUTO_EDIT_CALL_RESULTS/$BASE.json"
    ERROR="$AUTO_EDIT_CALL_ERRORS/$BASE.log"
    TMP_RESULT="$AUTO_EDIT_CALL_RESULTS/$BASE.tmp"

    if docker cp "$AUTO_EDIT_CALL_HELPER" rg-nas-mcp-hub:/tmp/rg_auto_edit_call.py >/dev/null 2>&1 \
      && docker cp "$REQ" rg-nas-mcp-hub:/tmp/rg_auto_edit_request.json >/dev/null 2>&1 \
      && docker exec rg-nas-mcp-hub python /tmp/rg_auto_edit_call.py /tmp/rg_auto_edit_request.json > "$TMP_RESULT" 2> "$ERROR"
    then
      mv -f "$TMP_RESULT" "$RESULT"
      rm -f "$ERROR" 2>/dev/null || true
    else
      rm -f "$TMP_RESULT" 2>/dev/null || true
    fi

    rm -f "$REQ" 2>/dev/null || true
    docker exec rg-nas-mcp-hub rm -f /tmp/rg_auto_edit_call.py /tmp/rg_auto_edit_request.json >/dev/null 2>&1 || true
  done
fi
