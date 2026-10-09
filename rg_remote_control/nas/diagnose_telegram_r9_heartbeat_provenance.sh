#!/bin/sh
# R9 read-only provenance audit. No network, containers, restarts or queue changes.
set -eu
ROOT=/volume1/docker
STATE="$ROOT/RG_NAS_STATE"
python3 - "$STATE" <<'PY'
import datetime, json, pathlib, sys, time
state=pathlib.Path(sys.argv[1])
now=time.time()
keys={
 "scheduler_last_check_at":"scheduler_tick",
 "telegram_control_plane_last_sync_at":"control_plane_sync",
 "rg_telegram_control_agent_last_run_at":"completed_control_request_only",
 "mcp_tick_heartbeat_at":"legacy_mcp_tick",
 "failover_heartbeat_at":"legacy_failover",
 "telegram_watchdog_script_checked_at":"r9_watchdog_execution",
 "telegram_watchdog_script_rc":"r9_watchdog_exit_code",
 "telegram_watchdog_status":"watchdog_health",
}
def read(name):
 p=state/name
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>4096:return None
  return p.read_text(encoding="utf-8",errors="replace").strip()
 except OSError:return None
def age(value):
 if not value:return None
 try:
  dt=datetime.datetime.fromisoformat(value.replace("Z","+00:00"))
  if dt.tzinfo is None:return None
  delta=now-dt.timestamp()
  return int(delta) if delta>=-60 else None
 except (ValueError,TypeError,OverflowError):return None
print("RG_R9_HEARTBEAT_PROVENANCE_READ_ONLY")
for key,owner in keys.items():
 v=read(key)
 data={"field":key,"owner":owner,"present":v is not None}
 if key.endswith("_rc") or key.endswith("_status"):
  data["value"]=v[:40] if v else "UNKNOWN"
 else:
  data["age_seconds"]=age(v)
 print(json.dumps(data,ensure_ascii=False,sort_keys=True))
print("NOTE control_agent_last_run_at_is_request_driven_not_scheduler_heartbeat")
print("NO_MUTATIONS_NO_NETWORK")
PY
