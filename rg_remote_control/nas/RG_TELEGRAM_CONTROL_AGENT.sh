#!/bin/sh
set -eu

ROOT="/volume1/docker"
REQ="$ROOT/RG_TELEGRAM/control-requests"
RES="$ROOT/RG_TELEGRAM/control-results"
ARCHIVE="$ROOT/RG_TELEGRAM/control-requests-done"
STATE="$ROOT/RG_NAS_STATE"
LOCK="$STATE/rg-telegram-control-agent.lock"
STALE=300

mkdir -p "$REQ" "$RES" "$ARCHIVE" "$STATE"

acquire_lock() {
  NOW="$(date +%s)"
  if mkdir "$LOCK" 2>/dev/null; then
    printf '%s\n' "$NOW" > "$LOCK/started_at"
    return 0
  fi
  START="$(cat "$LOCK/started_at" 2>/dev/null || echo 0)"
  case "$START" in ''|*[!0-9]*) START=0 ;; esac
  AGE=$((NOW-START))
  if [ "$START" -eq 0 ] || [ "$AGE" -ge "$STALE" ]; then
    rm -rf "$LOCK"
    mkdir "$LOCK"
    printf '%s\n' "$NOW" > "$LOCK/started_at"
    return 0
  fi
  return 1
}
acquire_lock || exit 0
trap 'rm -rf "$LOCK"; rm -f "$STATE"/.rgtc-agent.* 2>/dev/null || true' EXIT INT TERM

for FILE in "$REQ"/*.json; do
  [ -f "$FILE" ] || break
  META="$STATE/.rgtc-agent.meta.$$"
  if ! python3 - "$FILE" > "$META" <<'PY'
import json,sys
try:
    d=json.load(open(sys.argv[1],encoding="utf-8"))
except Exception:
    raise SystemExit(1)
jid=str(d.get("id") or "").strip()
action=str(d.get("action") or "").strip()
allowed={"scanner-run","telegram-watchdog-run","telegram-sync-run","telegram-audit","queues","doctor","control-app-install"}
if not jid or action not in allowed:
    raise SystemExit(2)
print(jid)
print(action)
PY
  then
    mv -f "$FILE" "$ARCHIVE/$(basename "$FILE").invalid" 2>/dev/null || rm -f "$FILE"
    continue
  fi

  ID="$(sed -n '1p' "$META")"
  ACTION="$(sed -n '2p' "$META")"
  OUT="$STATE/.rgtc-agent.out.$$"
  ERR="$STATE/.rgtc-agent.err.$$"
  STARTED="$(date -Iseconds)"
  RC=0

  case "$ACTION" in
    scanner-run)
      sh "$ROOT/RG_NAS_CONTROL.sh" scanner-run >"$OUT" 2>"$ERR" || RC=$?
      ;;
    telegram-watchdog-run)
      rm -rf "$STATE/telegram-watchdog.lock" 2>/dev/null || true
      sh "$ROOT/RG_NAS_TELEGRAM_WATCHDOG.sh" >"$OUT" 2>"$ERR" || RC=$?
      if [ "$RC" -eq 0 ]; then
        sh "$ROOT/RG_NAS_CONTROL.sh" telegram-watchdog >>"$OUT" 2>>"$ERR" || RC=$?
      fi
      ;;
    telegram-sync-run)
      sh "$ROOT/RG_NAS_CONTROL.sh" telegram-sync >"$OUT" 2>"$ERR" || RC=$?
      ;;
    telegram-audit)
      sh "$ROOT/RG_NAS_CONTROL.sh" doctor >"$OUT" 2>"$ERR" || RC=$?
      ;;
    queues)
      sh "$ROOT/RG_NAS_CONTROL.sh" queues >"$OUT" 2>"$ERR" || RC=$?
      ;;
    doctor)
      sh "$ROOT/RG_NAS_CONTROL.sh" doctor >"$OUT" 2>"$ERR" || RC=$?
      ;;
    control-app-install)
      sh "$ROOT/RG_TELEGRAM_CONTROL_APP_INSTALL.sh" >"$OUT" 2>"$ERR" || RC=$?
      ;;
  esac

  FINISHED="$(date -Iseconds)"
  RESULT_TMP="$RES/.$ID.tmp"
  python3 - "$ID" "$ACTION" "$RC" "$STARTED" "$FINISHED" "$OUT" "$ERR" > "$RESULT_TMP" <<'PY'
import json,pathlib,sys
jid,action,rc,started,finished,out_path,err_path=sys.argv[1:]
def read(path,limit=12000):
    try:
        return pathlib.Path(path).read_text(encoding="utf-8",errors="replace")[-limit:]
    except Exception:
        return ""
code=int(rc)
print(json.dumps({
  "version":1,"id":jid,"action":action,"status":"ok" if code==0 else "error",
  "exitCode":code,"startedAt":started,"finishedAt":finished,
  "output":read(out_path),"error":read(err_path,4000) or None
},ensure_ascii=False))
PY
  mv -f "$RESULT_TMP" "$RES/$ID.json"
  mv -f "$FILE" "$ARCHIVE/$(basename "$FILE")" 2>/dev/null || rm -f "$FILE"
  printf '%s\n' "$FINISHED" > "$STATE/rg_telegram_control_agent_last_run_at"
  printf '%s\n' "$ACTION" > "$STATE/rg_telegram_control_agent_last_action"
  printf '%s\n' "$RC" > "$STATE/rg_telegram_control_agent_last_rc"
  rm -f "$OUT" "$ERR" "$META"
done
