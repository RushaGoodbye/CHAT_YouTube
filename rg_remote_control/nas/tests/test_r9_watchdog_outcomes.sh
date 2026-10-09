#!/bin/sh
# R9 regression test: safe isolated watchdog outcome handling. No NAS, Docker, or network.
set -eu
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT HUP INT TERM
mkdir -p "$T/root" "$T/state"
NOW="2026-10-09T19:00:00+03:00"
probe() {
 ROOT="$T/root"; STATE="$T/state"
 if [ -f "$ROOT/RG_NAS_TELEGRAM_WATCHDOG.sh" ]; then
  if sh "$ROOT/RG_NAS_TELEGRAM_WATCHDOG.sh" > /dev/null 2>&1; then
   printf '%s\n' "0" > "$STATE/telegram_watchdog_script_rc"
   printf '%s\n' "$NOW" > "$STATE/telegram_watchdog_script_checked_at"
   rm -f "$STATE/telegram_watchdog_script_failed_at"
  else
   WATCHDOG_RC=$?
   printf '%s\n' "$WATCHDOG_RC" > "$STATE/telegram_watchdog_script_rc"
   printf '%s\n' "$NOW" > "$STATE/telegram_watchdog_script_checked_at"
   printf '%s\n' "$NOW" > "$STATE/telegram_watchdog_script_failed_at"
  fi
 else
  printf '%s\n' "127" > "$STATE/telegram_watchdog_script_rc"
  printf '%s\n' "$NOW" > "$STATE/telegram_watchdog_script_checked_at"
  printf '%s\n' "$NOW" > "$STATE/telegram_watchdog_script_failed_at"
 fi
}
probe
[ "$(cat "$T/state/telegram_watchdog_script_rc")" = "127" ]
printf '#!/bin/sh\nexit 42\n' > "$T/root/RG_NAS_TELEGRAM_WATCHDOG.sh"
probe
[ "$(cat "$T/state/telegram_watchdog_script_rc")" = "42" ]
[ -f "$T/state/telegram_watchdog_script_failed_at" ]
printf '#!/bin/sh\nexit 0\n' > "$T/root/RG_NAS_TELEGRAM_WATCHDOG.sh"
probe
[ "$(cat "$T/state/telegram_watchdog_script_rc")" = "0" ]
[ ! -f "$T/state/telegram_watchdog_script_failed_at" ]
echo "R9_WATCHDOG_OUTCOME_REGRESSION_PASS"
