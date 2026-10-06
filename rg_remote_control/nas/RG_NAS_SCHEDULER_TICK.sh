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

if [ -f "$ROOT/RG_TELEGRAM_CONTROL_AGENT.sh" ]; then
  sh "$ROOT/RG_TELEGRAM_CONTROL_AGENT.sh" >> "$STATE/rg-telegram-control-agent.log" 2>&1 || true
fi

if [ -f "$ROOT/RG_NAS_TELEGRAM_WATCHDOG.sh" ]; then
  sh "$ROOT/RG_NAS_TELEGRAM_WATCHDOG.sh" >> "$STATE/telegram-watchdog.log" 2>&1 || true
fi
if [ -f "$ROOT/RG_NAS_TELEGRAM_CONTROL_PLANE.sh" ]; then
  sh "$ROOT/RG_NAS_TELEGRAM_CONTROL_PLANE.sh" >> "$STATE/telegram-control-plane.log" 2>&1 || true
fi

if [ -f "$ROOT/RG_NAS_COMMAND_BUS.sh" ]; then
  if sh -n "$ROOT/RG_NAS_COMMAND_BUS.sh" >/dev/null 2>&1; then
    sh "$ROOT/RG_NAS_COMMAND_BUS.sh" >> "$STATE/nas-command-bus.log" 2>&1 || true
    rm -f "$STATE/nas_command_bus_error" 2>/dev/null || true
  else
    printf '%s\n' "command_bus_syntax_error" > "$STATE/nas_command_bus_error"
  fi
fi

AUTODEPLOY="$ROOT/RG_NAS_AUTO_DEPLOY.sh"
if [ ! -x "$AUTODEPLOY" ]; then
  printf '%s\n' "ERROR" > "$STATE/scheduler_last_check_status"
  printf '%s\n' "autodeploy_script_missing" > "$STATE/scheduler_dispatch_error"
  exit 1
fi

# Synology Task Scheduler is the single owner. Run the deploy script directly
# on the NAS host; the deploy script has its own lock and safely exits when
# another deploy is already active. This removes rg-nas-autodeploy as a
# critical dependency.
if RG_AUTODEPLOY_OWNER=scheduler "$AUTODEPLOY" >> "$LOG" 2>&1; then
  printf '%s\n' "$NOW" > "$STATE/scheduler_dispatch_ok_at"
  printf '%s\n' "OK" > "$STATE/scheduler_last_check_status"
  rm -f "$STATE/scheduler_dispatch_error" 2>/dev/null || true
  exit 0
fi

printf '%s\n' "ERROR" > "$STATE/scheduler_last_check_status"
printf '%s\n' "host_autodeploy_failed" > "$STATE/scheduler_dispatch_error"
exit 1
