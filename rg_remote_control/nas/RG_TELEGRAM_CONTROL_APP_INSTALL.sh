#!/bin/sh
set -eu

ROOT="/volume1/docker"
APP_ROOT="$ROOT/RG_TELEGRAM_CONTROL"
STATE="$ROOT/RG_NAS_STATE"
SOURCE_ROOT="${RG_SOURCE_ROOT:-${1:-}}"
TOKEN_FILE="$ROOT/RG_SECRETS/github_token"
REPO="RushaGoodbye/rasha-goodbye-news-bot"
REF="${RG_TELEGRAM_CONTROL_REF:-main}"
PORT_FILE="$STATE/rg_telegram_control_app_port"
STATUS_FILE="$STATE/rg_telegram_control_app_status"
INSTALL_LOG="$STATE/rg-telegram-control-install.log"

mkdir -p "$APP_ROOT/data" "$APP_ROOT/source" "$ROOT/RG_TELEGRAM/control-requests" "$ROOT/RG_TELEGRAM/control-results" "$STATE"
rm -f "$STATUS_FILE" "$STATE/rg_telegram_control_app_error_at" "$STATE/rg_telegram_control_app_last_error" 2>/dev/null || true

fail_install() {
  CODE="${1:-1}"
  MSG="${2:-install_failed}"
  printf '%s\n' "ERROR" > "$STATUS_FILE"
  printf '%s\n' "$(date -Iseconds)" > "$STATE/rg_telegram_control_app_error_at"
  printf '%s\n' "$MSG" > "$STATE/rg_telegram_control_app_last_error"
  [ -f "$INSTALL_LOG" ] && tail -n 200 "$INSTALL_LOG" || true
  exit "$CODE"
}

port_free() {
  python3 - "$1" <<'PY'
import socket,sys
port=int(sys.argv[1])
s=socket.socket()
try:
    s.bind(("0.0.0.0",port))
except OSError:
    raise SystemExit(1)
finally:
    try: s.close()
    except Exception: pass
raise SystemExit(0)
PY
}

PORT=""
for CANDIDATE in 18788 18789 18790 18888 18988; do
  if port_free "$CANDIDATE"; then
    PORT="$CANDIDATE"
    break
  fi
done
[ -n "$PORT" ] || fail_install 11 "no_free_control_port"
printf '%s\n' "$PORT" > "$PORT_FILE"
export RGTC_HOST_PORT="$PORT"

TMP="$APP_ROOT/source.new.$$"
rm -rf "$TMP"
mkdir -p "$TMP"

if [ -n "$SOURCE_ROOT" ] && [ -f "$SOURCE_ROOT/rg-telegram-control/Dockerfile" ]; then
  cp -pR "$SOURCE_ROOT/rg-telegram-control/." "$TMP/"
else
  [ -s "$TOKEN_FILE" ] || fail_install 2 "github_token_missing"
  TOKEN="$(tr -d '\r\n ' < "$TOKEN_FILE")"
  API="https://api.github.com/repos/$REPO/contents/rg-telegram-control"
  fetch_file() {
    REL="$1"
    OUT="$2"
    mkdir -p "$(dirname "$OUT")"
    curl -fsSL --connect-timeout 10 --max-time 45 \
      -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/vnd.github.raw+json" \
      -H "User-Agent: RG-Telegram-Control-Installer/1.1" \
      "$API/$REL?ref=$REF" -o "$OUT"
  }
  fetch_file Dockerfile "$TMP/Dockerfile" || fail_install 21 "fetch_Dockerfile_failed"
  fetch_file compose.yaml "$TMP/compose.yaml" || fail_install 22 "fetch_compose_failed"
  fetch_file requirements.txt "$TMP/requirements.txt" || fail_install 23 "fetch_requirements_failed"
  fetch_file README.md "$TMP/README.md" || fail_install 24 "fetch_README_failed"
  fetch_file app/main.py "$TMP/app/main.py" || fail_install 25 "fetch_main_failed"
  fetch_file app/static/index.html "$TMP/app/static/index.html" || fail_install 26 "fetch_index_failed"
fi

[ -f "$TMP/Dockerfile" ] || fail_install 3 "Dockerfile_missing"
[ -f "$TMP/compose.yaml" ] || fail_install 4 "compose_missing"

rm -rf "$APP_ROOT/source.old"
[ -d "$APP_ROOT/source" ] && mv "$APP_ROOT/source" "$APP_ROOT/source.old" || true
mv "$TMP" "$APP_ROOT/source"

cd "$APP_ROOT/source"
docker rm -f rg-telegram-control >/dev/null 2>&1 || true

: > "$INSTALL_LOG"
if docker compose version >/dev/null 2>&1; then
  if ! docker compose -p rg-telegram-control up -d --build >"$INSTALL_LOG" 2>&1; then
    fail_install 31 "docker_compose_up_failed"
  fi
elif command -v docker-compose >/dev/null 2>&1; then
  if ! docker-compose -p rg-telegram-control up -d --build >"$INSTALL_LOG" 2>&1; then
    fail_install 32 "docker_compose_up_failed"
  fi
else
  fail_install 33 "docker_compose_unavailable"
fi

OK=0
I=0
while [ "$I" -lt 30 ]; do
  if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/healthz" >/tmp/rg-telegram-control-health.$$ 2>/dev/null \
     && grep -q '"ok":true' /tmp/rg-telegram-control-health.$$; then
    OK=1
    break
  fi
  I=$((I+1))
  sleep 2
done
rm -f /tmp/rg-telegram-control-health.$$ 2>/dev/null || true

if [ "$OK" -ne 1 ]; then
  docker logs --tail 100 rg-telegram-control >>"$INSTALL_LOG" 2>&1 || true
  fail_install 5 "health_check_failed"
fi

printf '%s\n' "OK" > "$STATUS_FILE"
printf '%s\n' "$(date -Iseconds)" > "$STATE/rg_telegram_control_app_checked_at"
printf '%s\n' "$(date -Iseconds)" > "$STATE/rg_telegram_control_app_deployed_at"
rm -f "$STATE/rg_telegram_control_app_error_at" "$STATE/rg_telegram_control_app_last_error" 2>/dev/null || true
echo "RG_TELEGRAM_CONTROL_APP_OK port=$PORT"
