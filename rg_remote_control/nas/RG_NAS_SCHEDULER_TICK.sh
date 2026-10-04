#!/bin/sh
set -eu

ROOT="/volume1/docker"
STATE="$ROOT/RG_NAS_STATE"
EXECUTOR="rg-nas-autodeploy"
LOG="$STATE/auto-deploy.log"

mkdir -p "$STATE"
NOW="$(date -Iseconds)"
printf '%s\n' "$NOW" > "$STATE/scheduler_last_check_at"
printf '%s\n' "RUNNING" > "$STATE/scheduler_last_check_status"
printf '%s\n' "$NOW" > "$STATE/scheduler_dispatch_at"

if [ -f "$ROOT/RG_NAS_COMMAND_BUS.sh" ]; then
  if sh -n "$ROOT/RG_NAS_COMMAND_BUS.sh" >/dev/null 2>&1; then
    sh "$ROOT/RG_NAS_COMMAND_BUS.sh" >> "$STATE/nas-command-bus.log" 2>&1 || true
    rm -f "$STATE/nas_command_bus_error" 2>/dev/null || true
  else
    printf '%s\n' "command_bus_syntax_error" > "$STATE/nas_command_bus_error"
  fi
fi

MCP_DIR="/volume1/RG_AUTO_EDIT/REMOTE_MCP/SOURCE"
MCP_REQUEST="/volume1/RG_AUTO_EDIT/REMOTE_MCP/DEPLOY_REQUEST"
MCP_STATUS="$STATE/mcp_deploy_status"
MCP_LOG="$STATE/mcp-deploy.log"

if [ -f "$MCP_REQUEST" ]; then
  printf '%s\n' "RUNNING" > "$MCP_STATUS"
  if [ -f "$MCP_DIR/docker-compose.yml" ]; then
    if docker compose version >/dev/null 2>&1; then
      if docker compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" up -d --build > "$MCP_LOG" 2>&1; then
        docker compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" ps >> "$MCP_LOG" 2>&1 || true
        printf '%s\n' "OK" > "$MCP_STATUS"
      else
        printf '%s\n' "ERROR" > "$MCP_STATUS"
      fi
    elif command -v docker-compose >/dev/null 2>&1; then
      if docker-compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" up -d --build > "$MCP_LOG" 2>&1; then
        docker-compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" ps >> "$MCP_LOG" 2>&1 || true
        printf '%s\n' "OK" > "$MCP_STATUS"
      else
        printf '%s\n' "ERROR" > "$MCP_STATUS"
      fi
    else
      printf '%s\n' "Docker Compose is unavailable" > "$MCP_LOG"
      printf '%s\n' "ERROR" > "$MCP_STATUS"
    fi
  else
    printf '%s\n' "Missing $MCP_DIR/docker-compose.yml" > "$MCP_LOG"
    printf '%s\n' "ERROR" > "$MCP_STATUS"
  fi
  rm -f "$MCP_REQUEST" 2>/dev/null || true
fi

RUNNING="$(docker inspect -f '{{.State.Running}}' "$EXECUTOR" 2>/dev/null || echo false)"
if [ "$RUNNING" != "true" ]; then
  printf '%s\n' "ERROR" > "$STATE/scheduler_last_check_status"
  printf '%s\n' "executor_not_running" > "$STATE/scheduler_dispatch_error"
  exit 1
fi

if docker exec -d "$EXECUTOR" /bin/sh -c "RG_AUTODEPLOY_OWNER=scheduler RG_AUTODEPLOY_EXECUTOR=1 $ROOT/RG_NAS_AUTO_DEPLOY.sh >> $LOG 2>&1"; then
  printf '%s\n' "$NOW" > "$STATE/scheduler_dispatch_ok_at"
  rm -f "$STATE/scheduler_dispatch_error" 2>/dev/null || true
  exit 0
fi

printf '%s\n' "ERROR" > "$STATE/scheduler_last_check_status"
printf '%s\n' "docker_exec_failed" > "$STATE/scheduler_dispatch_error"
exit 1
