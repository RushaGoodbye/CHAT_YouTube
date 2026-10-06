#!/bin/sh
set -eu

ROOT="/volume1/docker"
APP_ROOT="$ROOT/RG_TELEGRAM_CONTROL"
STATE="$ROOT/RG_NAS_STATE"
SOURCE_ROOT="${RG_SOURCE_ROOT:-${1:-}}"
TOKEN_FILE="$ROOT/RG_SECRETS/github_token"
REPO="RushaGoodbye/rasha-goodbye-news-bot"
REF="${RG_TELEGRAM_CONTROL_REF:-main}"

mkdir -p "$APP_ROOT/data" "$APP_ROOT/source" "$ROOT/RG_TELEGRAM/control-requests" "$ROOT/RG_TELEGRAM/control-results"
TMP="$APP_ROOT/source.new.$"
rm -rf "$TMP"
mkdir -p "$TMP"

if [ -n "$SOURCE_ROOT" ] && [ -f "$SOURCE_ROOT/rg-telegram-control/Dockerfile" ]; then
  cp -pR "$SOURCE_ROOT/rg-telegram-control/." "$TMP/"
else
  [ -s "$TOKEN_FILE" ] || { echo "GitHub token missing for standalone RG Telegram Control install" >&2; exit 2; }
  TOKEN="$(tr -d '\r\n ' < "$TOKEN_FILE")"
  API="https://api.github.com/repos/$REPO/contents/rg-telegram-control"
  fetch_file() {
    REL="$1"
    OUT="$2"
    mkdir -p "$(dirname "$OUT")"
    curl -fsSL --connect-timeout 10 --max-time 45 \
      -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/vnd.github.raw+json" \
      -H "User-Agent: RG-Telegram-Control-Installer/1.0" \
      "$API/$REL?ref=$REF" -o "$OUT"
  }
  fetch_file Dockerfile "$TMP/Dockerfile"
  fetch_file compose.yaml "$TMP/compose.yaml"
  fetch_file requirements.txt "$TMP/requirements.txt"
  fetch_file README.md "$TMP/README.md"
  fetch_file app/main.py "$TMP/app/main.py"
  fetch_file app/static/index.html "$TMP/app/static/index.html"
fi

[ -f "$TMP/Dockerfile" ] || { echo "RG Telegram Control Dockerfile missing" >&2; exit 3; }
[ -f "$TMP/compose.yaml" ] || { echo "RG Telegram Control compose missing" >&2; exit 4; }
rm -rf "$APP_ROOT/source.old"
[ -d "$APP_ROOT/source" ] && mv "$APP_ROOT/source" "$APP_ROOT/source.old" || true
mv "$TMP" "$APP_ROOT/source"

cd "$APP_ROOT/source"
if docker compose version >/dev/null 2>&1; then
  docker compose -p rg-telegram-control up -d --build
else
  docker-compose -p rg-telegram-control up -d --build
fi

OK=0
I=0
while [ "$I" -lt 30 ]; do
  if curl -fsS --max-time 3 http://127.0.0.1:8788/healthz >/tmp/rg-telegram-control-health.$$ 2>/dev/null \
     && grep -q '"ok":true' /tmp/rg-telegram-control-health.$$; then
    OK=1
    break
  fi
  I=$((I+1))
  sleep 2
done
rm -f /tmp/rg-telegram-control-health.$$ 2>/dev/null || true

if [ "$OK" -ne 1 ]; then
  printf '%s\n' "ERROR" > "$STATE/rg_telegram_control_app_status"
  printf '%s\n' "$(date -Iseconds)" > "$STATE/rg_telegram_control_app_error_at"
  docker logs --tail 100 rg-telegram-control 2>/dev/null || true
  exit 5
fi

printf '%s\n' "OK" > "$STATE/rg_telegram_control_app_status"
printf '%s\n' "$(date -Iseconds)" > "$STATE/rg_telegram_control_app_checked_at"
printf '%s\n' "8788" > "$STATE/rg_telegram_control_app_port"
rm -f "$STATE/rg_telegram_control_app_error_at" 2>/dev/null || true
echo "RG_TELEGRAM_CONTROL_APP_OK port=8788"
