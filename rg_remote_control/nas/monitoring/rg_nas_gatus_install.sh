#!/bin/sh
# Isolated Gatus monitor only. Does not touch Telegram or Cloudflare.
set -eu
umask 077
REF="$1"
if ! printf '%s' "$REF" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "ERROR: pass exact 40-character Git commit SHA" >&2; exit 2
fi
[ "$(id -u)" -eq 0 ] || { echo "ERROR: sudo required" >&2; exit 2; }
ROOT="/volume1/docker"
DEST="$ROOT/RG_NAS_MONITOR"
PROJECT="rg-nas-monitor"
for cmd in docker curl python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: missing $cmd" >&2; exit 2; }
done
docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon unavailable" >&2; exit 2; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose unavailable" >&2; exit 2; }
[ -d "$ROOT/RG_NAS_STATE" ] || { echo "ERROR: live NAS state missing" >&2; exit 2; }
[ ! -e "$DEST" ] || { echo "ERROR: monitor dir already exists; no overwrite" >&2; exit 3; }
for name in rg-nas-gatus rg-nas-gatus-observer; do
  if docker inspect "$name" >/dev/null 2>&1; then
    echo "ERROR: container $name already exists" >&2
    exit 3
  fi
done
if command -v ss >/dev/null 2>&1 && ss -ltn | grep -Eq '(:18080[[:space:]])'; then
  echo "ERROR: port 18080 is busy" >&2
  exit 3
fi
TEMP="$(mktemp -d "$ROOT/.rg-nas-gatus-install.XXXXXX")"
trap 'rm -rf "$TEMP"' EXIT
trap 'exit 1' HUP INT TERM
BASE="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$REF/rg_remote_control/nas/monitoring"
for name in config.yaml compose.yaml rg_nas_gatus_observer_v1.py; do
  curl -fsSL --connect-timeout 8 --max-time 45 "$BASE/$name" -o "$TEMP/$name"
  [ -s "$TEMP/$name" ] || { echo "ERROR: empty $name" >&2; exit 4; }
done
python3 -m py_compile "$TEMP/rg_nas_gatus_observer_v1.py"
grep -q '127.0.0.1:18080:8080' "$TEMP/compose.yaml"
grep -q 'RG_NAS_STATE:/nas/RG_NAS_STATE:ro' "$TEMP/compose.yaml"
python3 - "$TEMP" <<'PY'
from pathlib import Path
import secrets, sys
directory = Path(sys.argv[1])
token = secrets.token_urlsafe(40)
for name, value in (("token", token+"\n"), (".env", "GATUS_MONITOR_TOKEN="+token+"\n")):
    file = directory / name
    file.write_text(value, encoding="utf-8")
    file.chmod(0o600)
PY
mkdir "$TEMP/data"
printf '%s\n' "$REF" > "$TEMP/.rg_gatus_managed"
(cd "$TEMP" && docker compose -p "$PROJECT" -f compose.yaml config -q)
mv "$TEMP" "$DEST"
# The cleanup trap must not delete the installed directory.
TEMP="$(mktemp -d "$ROOT/.rg-nas-gatus-cleanup.XXXXXX")"
if ! (cd "$DEST" && docker compose -p "$PROJECT" -f compose.yaml up -d); then
  (cd "$DEST" && docker compose -p "$PROJECT" -f compose.yaml down) || true
  echo "ERROR: monitor startup failed; monitor containers rolled back" >&2
  exit 5
fi
sleep 5
for name in rg-nas-gatus rg-nas-gatus-observer; do
  running="$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || echo false)"
  if [ "$running" != true ]; then
    (cd "$DEST" && docker compose -p "$PROJECT" -f compose.yaml down) || true
    echo "ERROR: failed to start $name; monitor containers rolled back" >&2
    exit 5
  fi
done
if ! curl -fsS --max-time 10 http://127.0.0.1:18080/ >/dev/null; then
  (cd "$DEST" && docker compose -p "$PROJECT" -f compose.yaml down) || true
  echo "ERROR: dashboard unavailable; monitor containers rolled back" >&2
  exit 5
fi
echo "RG_NAS_GATUS_INSTALLED=YES"
echo "GATUS_LOCAL_DASHBOARD=http://127.0.0.1:18080"
echo "OBSERVER=RUNNING"
echo "PUBLIC_TELEGRAM=UNCHANGED"
echo "CLOUDFLARE=UNCHANGED"
