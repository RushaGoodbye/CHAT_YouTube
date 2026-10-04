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
