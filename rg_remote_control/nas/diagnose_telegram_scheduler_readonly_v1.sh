#!/bin/sh
# RG Telegram Scheduler diagnosis. READ-ONLY: no service changes, no queues, no restarts.
set -u
ROOT="/volume1/docker"
STATE="$ROOT/RG_NAS_STATE"
echo "=== RG TELEGRAM SCHEDULER READ-ONLY DIAGNOSTIC V1 ==="
echo "NAS_TIME=$(date -Iseconds 2>/dev/null || date)"
echo "NAS_UPTIME=$(uptime 2>/dev/null | cut -c 1-160)"
if [ "$(id -u)" -ne 0 ]; then
  echo "NEEDS_ROOT=sudo sh"
  exit 2
fi

for f in RG_NAS_SCHEDULER_TICK.sh RG_NAS_AUTO_DEPLOY.sh RG_NAS_TELEGRAM_WATCHDOG.sh RG_NAS_TELEGRAM_CONTROL_PLANE.sh RG_TELEGRAM_CONTROL_AGENT.sh; do
  p="$ROOT/$f"
  if [ -f "$p" ]; then
    if sh -n "$p" 2>/dev/null; then syntax=OK; else syntax=ERROR; fi
    if [ -x "$p" ]; then executable=YES; else executable=NO; fi
    echo "SCRIPT $f present=YES executable=$executable syntax=$syntax"
  else
    echo "SCRIPT $f present=NO"
  fi
done

# Count only occurrences of the exact RG scheduler name. Do not output other cron jobs.
for f in /etc/crontab /var/spool/cron/crontabs/root /var/spool/cron/root /usr/syno/etc/synoschedtask.conf /etc/synoschedtask.conf; do
  if [ -r "$f" ]; then
    n="$(grep -c 'RG_NAS_SCHEDULER_TICK' "$f" 2>/dev/null || true)"
    echo "TASK_REFERENCE $f count=${n:-0}"
  fi
done
if command -v crontab >/dev/null 2>&1; then
  n="$(crontab -l 2>/dev/null | grep -c 'RG_NAS_SCHEDULER_TICK' || true)"
  echo "TASK_REFERENCE root_crontab count=${n:-0}"
fi
SYNOSCHED=""
for p in /usr/syno/bin/synoschedtask /usr/syno/sbin/synoschedtask; do
  if [ -x "$p" ]; then SYNOSCHED="$p"; break; fi
done
if [ -n "$SYNOSCHED" ]; then
  n="$("$SYNOSCHED" --enum 2>/dev/null | grep -ci 'RG_NAS_SCHEDULER_TICK\|RG NAS SCHEDULER' || true)"
  echo "TASK_REFERENCE synoschedtask_enum count=${n:-0} (informational; enum format varies)"
fi

if command -v python3 >/dev/null 2>&1; then
  python3 - "$STATE" <<'PY'
import os, sys, time, re, stat
from pathlib import Path
root=Path(sys.argv[1])
names=[
 "scheduler_last_check_at","scheduler_last_check_status","scheduler_dispatch_at",
 "scheduler_dispatch_ok_at","scheduler_dispatch_error","mcp_tick_heartbeat_at",
 "telegram_control_plane_last_sync_at","telegram_control_plane_status",
 "telegram_watchdog_status","rg_telegram_control_app_status",
 "rg_telegram_control_app_version","rg_telegram_control_agent_last_action",
 "rg_telegram_control_agent_last_rc","rg_telegram_control_agent_last_run_at",
 "nas_command_bus_error","last_deploy_status","live_smoke_status"]
safe=re.compile(r"^[a-zA-Z0-9_ .:+/=-]{0,160}$")
print("=== STATE FILES ===")
for name in names:
    p=root/name
    try:
        m=p.lstat()
        if not stat.S_ISREG(m.st_mode) or m.st_size>512:
            print(f"STATE {name} invalid_or_oversized")
            continue
        data=p.read_text(encoding="utf-8",errors="replace").strip()
        if not safe.fullmatch(data) or re.search(r"token|secret|password|Bearer",data,re.I):
            data="[REDACTED]"
        age=max(0,int(time.time()-m.st_mtime))
        print(f"STATE {name} age_sec={age} value={data[:160]}")
    except OSError:
        print(f"STATE {name} MISSING")
PY
else
  echo "PYTHON3=NOT_AVAILABLE"
fi

DOCKER=""
for p in /usr/local/bin/docker /usr/bin/docker /bin/docker /var/packages/ContainerManager/target/usr/bin/docker /var/packages/Docker/target/usr/bin/docker; do
  if [ -x "$p" ]; then DOCKER="$p"; break; fi
done
if [ -n "$DOCKER" ]; then
  echo "=== DOCKER CONTAINER STATES ==="
  for name in rg-telegram-control rg-nas-mcp-hub rg-openai-tunnel-telegram-readonly rg-telegram-tunnel-reader rg-nas-autodeploy; do
    value="$("$DOCKER" inspect -f '{{.State.Status}}' "$name" 2>/dev/null || true)"
    echo "CONTAINER $name status=${value:-NOT_FOUND}"
  done
else
  echo "DOCKER=NOT_AVAILABLE"
fi
PORT="$(cat "$STATE/rg_telegram_control_app_port" 2>/dev/null || true)"
case "$PORT" in
  ''|*[!0-9]*) echo "CONTROL_APP_HEALTH=PORT_UNKNOWN" ;;
  *)
    if curl -fsS --max-time 4 "http://127.0.0.1:$PORT/healthz" 2>/dev/null | grep -q '"ok":true'; then
      echo "CONTROL_APP_HEALTH=OK"
    else
      echo "CONTROL_APP_HEALTH=ERROR_OR_UNKNOWN"
    fi
    ;;
esac
echo "=== DIAGNOSTIC COMPLETE; NO CHANGES MADE ==="
