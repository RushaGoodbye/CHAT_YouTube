#!/bin/sh
set -eu

ROOT="/volume1/docker"
STATE="$ROOT/RG_NAS_STATE"
LOG="$STATE/auto-deploy.log"

mkdir -p "$STATE"
NOW="$(date -Iseconds)"
printf '%s\n' "$NOW" > "$STATE/scheduler_last_check_at"
printf '%s\n' "RUNNING" > "$STATE/scheduler_last_check_status"
printf '%s\n' "$NOW" > "$STATE/scheduler_dispatch_at"

# Synology Task Scheduler is the only deploy owner. Remove the obsolete
# restart-policy container so it cannot enter a restart loop or race the host scheduler.
if docker inspect rg-nas-autodeploy >/dev/null 2>&1; then
  docker update --restart=no rg-nas-autodeploy >/dev/null 2>&1 || true
  docker rm -f rg-nas-autodeploy >/dev/null 2>&1 || true
  printf '%s\n' "$NOW" > "$STATE/obsolete_autodeploy_removed_at"
fi

TELEGRAM_CHECK_FAILED=0
# Unique temporary path prevents concurrent task runs from mixing failure lists.
FAILED_TMP="$STATE/telegram_scheduler_components_failed.$$"
trap 'rm -f "$FAILED_TMP"' EXIT
trap 'exit 1' HUP INT TERM
: > "$FAILED_TMP"
if [ -f "$ROOT/RG_TELEGRAM_CONTROL_AGENT.sh" ]; then
  sh "$ROOT/RG_TELEGRAM_CONTROL_AGENT.sh" >> "$STATE/rg-telegram-control-agent.log" 2>&1 || { TELEGRAM_CHECK_FAILED=1; echo control_agent >> "$FAILED_TMP"; }
else
  TELEGRAM_CHECK_FAILED=1
  echo control_agent_missing >> "$FAILED_TMP"
fi

if [ -f "$ROOT/RG_NAS_TELEGRAM_WATCHDOG.sh" ]; then
  sh "$ROOT/RG_NAS_TELEGRAM_WATCHDOG.sh" >> "$STATE/telegram-watchdog.log" 2>&1 || { TELEGRAM_CHECK_FAILED=1; echo watchdog >> "$FAILED_TMP"; }
else
  TELEGRAM_CHECK_FAILED=1
  echo watchdog_missing >> "$FAILED_TMP"
fi
if [ -f "$ROOT/RG_NAS_TELEGRAM_CONTROL_PLANE.sh" ]; then
  sh "$ROOT/RG_NAS_TELEGRAM_CONTROL_PLANE.sh" >> "$STATE/telegram-control-plane.log" 2>&1 || { TELEGRAM_CHECK_FAILED=1; echo control_plane >> "$FAILED_TMP"; }
else
  TELEGRAM_CHECK_FAILED=1
  echo control_plane_missing >> "$FAILED_TMP"
fi

if [ -f "$ROOT/RG_NAS_COMMAND_BUS.sh" ]; then
  if sh -n "$ROOT/RG_NAS_COMMAND_BUS.sh" >/dev/null 2>&1; then
    if sh "$ROOT/RG_NAS_COMMAND_BUS.sh" >> "$STATE/nas-command-bus.log" 2>&1; then
      rm -f "$STATE/nas_command_bus_error" 2>/dev/null || true
    else
      printf '%s\n' "command_bus_runtime_error" > "$STATE/nas_command_bus_error"
      TELEGRAM_CHECK_FAILED=1
      echo command_bus_runtime >> "$FAILED_TMP"
    fi
  else
    printf '%s\n' "command_bus_syntax_error" > "$STATE/nas_command_bus_error"
    TELEGRAM_CHECK_FAILED=1
    echo command_bus_syntax >> "$FAILED_TMP"
  fi
else
  printf '%s\n' "command_bus_missing" > "$STATE/nas_command_bus_error"
  TELEGRAM_CHECK_FAILED=1
  echo command_bus_missing >> "$FAILED_TMP"
fi

# Publish a separate, durable component result: deploy success does not imply Telegram health.
printf "%s\n" "$NOW" > "$STATE/telegram_scheduler_components_checked_at"
if [ "$TELEGRAM_CHECK_FAILED" -eq 0 ]; then
  printf "%s\n" "OK" > "$STATE/telegram_scheduler_components_status"
  rm -f "$STATE/telegram_scheduler_components_failed"
else
  printf "%s\n" "ERROR" > "$STATE/telegram_scheduler_components_status"
  mv -f "$FAILED_TMP" "$STATE/telegram_scheduler_components_failed"
fi
# Remaining per-process temp file is cleaned by EXIT trap.
# RG_KYIV_SHADOW_POLL_BEGIN
# Read-only Kyiv alert sampler. It never sends Telegram messages.
# Ubilling cache and 429 cooldown are enforced inside the Python adapter.
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_kyiv_ubilling_live_shadow_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_kyiv_ubilling_live_shadow_v1.py" once >> "$ROOT/RG_TELEGRAM_STATE/kyiv_shadow.log" 2>&1 || true
fi
# RG_KYIV_SHADOW_POLL_END

# RG_MODERATION_SHADOW_PROJECTION_V1
# Read-only event projection; no Bot API sends and no Cloudflare calls.
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_moderation_projection_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_moderation_projection_v1.py" once >> "$ROOT/RG_TELEGRAM_STATE/moderation_shadow.log" 2>&1 || true
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
if RG_AUTODEPLOY_OWNER=scheduler RG_AUTODEPLOY_EXECUTOR=1 "$AUTODEPLOY" >> "$LOG" 2>&1; then
  printf '%s\n' "$NOW" > "$STATE/scheduler_dispatch_ok_at"
  printf '%s\n' "OK" > "$STATE/scheduler_last_check_status"
  rm -f "$STATE/scheduler_dispatch_error" 2>/dev/null || true
  exit 0
fi

printf '%s\n' "ERROR" > "$STATE/scheduler_last_check_status"
printf '%s\n' "host_autodeploy_failed" > "$STATE/scheduler_dispatch_error"
exit 1
