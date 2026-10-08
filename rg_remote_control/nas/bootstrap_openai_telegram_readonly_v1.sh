#!/bin/sh
# Replace successful OpenAI MCP demo with a SAFE read-only Telegram status reader.
# This script never invokes or rebuilds the production bot/hub/YouTube/AutoEdit.
set -eu
DOCKER=""
for p in /usr/local/bin/docker /usr/bin/docker /bin/docker /var/packages/ContainerManager/target/usr/bin/docker /var/packages/Docker/target/usr/bin/docker; do
  if [ -x "$p" ]; then DOCKER="$p"; break; fi
done
[ "$(id -u)" -eq 0 ] || { echo "RUN AS ROOT (sudo sh)"; exit 1; }
[ -n "$DOCKER" ] || { echo "Docker CLI not found"; exit 1; }
export PATH="$(dirname "$DOCKER"):/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
"$DOCKER" info >/dev/null 2>&1 || { echo "Docker daemon not reachable"; exit 1; }

ROOT="/volume1/docker/RG_NAS_MCP/OPENAI_TUNNEL"
SOURCE="$ROOT/telegram_readonly_v1"
KEY="$ROOT/runtime_key"
STATE="/volume1/docker/RG_NAS_STATE"
OLD="rg-openai-tunnel-demo"
NEW="rg-openai-tunnel-telegram-readonly"
READER="rg-telegram-tunnel-reader"
IMAGE="ghcr.io/openai/tunnel-client:v0.0.16"
READER_IMAGE="rg-telegram-tunnel-reader:0.1.0"
REF="b355538109897df8657a393d5c9a068753f86ffa"
BASE="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$REF/rg_remote_control/nas/telegram_tunnel_readonly"
umask 077
[ -s "$KEY" ] || { echo "Existing runtime key missing. Refusing changes."; exit 1; }
[ -d "$STATE" ] || { echo "Synology state directory missing. Refusing changes."; exit 1; }
[ "$("$DOCKER" inspect -f '{{.State.Running}}' "$OLD" 2>/dev/null || true)" = "true" ] || {
  echo "Original demo tunnel is not running. Refusing changes."; exit 1;
}
if "$DOCKER" container inspect "$NEW" >/dev/null 2>&1; then
  echo "Read-only tunnel container already exists; refusing changes."; exit 1
fi
if "$DOCKER" container inspect "$READER" >/dev/null 2>&1; then
  echo "Reader container already exists; refusing changes."; exit 1
fi

TUNNEL_ID="$("$DOCKER" inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$OLD" |
  sed -n 's/^CONTROL_PLANE_TUNNEL_ID=//p' | head -n 1)"
case "$TUNNEL_ID" in tunnel_*) ;; *) echo "Tunnel ID not found; refusing changes"; exit 1 ;; esac

echo "STAGE 1/4: download pinned read-only reader source"
mkdir -p "$SOURCE"
chmod 700 "$SOURCE"
for file in app.py status_reader.py smoke.py Dockerfile; do
  curl -fSL --retry 2 --connect-timeout 10 --max-time 75 "$BASE/$file" -o "$SOURCE/$file.tmp"
  mv "$SOURCE/$file.tmp" "$SOURCE/$file"
done
echo "STAGE 2/4: build isolated reader Docker image"
"$DOCKER" build --pull -t "$READER_IMAGE" "$SOURCE"

echo "STAGE 3/4: start reader without any production bot writes or Docker socket"
"$DOCKER" run -d \
  --name "$READER" --restart unless-stopped --network host \
  --user 0:0 --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --cpus 1.0 --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --mount "type=bind,src=$STATE,dst=/state,readonly" \
  "$READER_IMAGE" >/dev/null

n=0
until "$DOCKER" exec "$READER" python /srv/telegram_reader/smoke.py >/dev/null 2>&1; do
  n=$((n+1))
  if [ "$n" -ge 15 ]; then
    echo "READER SMOKE FAILED. Demo tunnel still running; not switching."
    "$DOCKER" logs --tail 15 "$READER" 2>&1 | sed -E 's/(sk-[a-zA-Z0-9_-]{8,})/[REDACTED]/g' || true
    "$DOCKER" rm -f "$READER" >/dev/null 2>&1 || true
    exit 1
  fi
  sleep 2
done
"$DOCKER" exec "$READER" python /srv/telegram_reader/smoke.py

echo "STAGE 4/4: atomically switch tunnel; rollback to demo if readiness fails"
"$DOCKER" stop "$OLD" >/dev/null
RESTORE=1
restore_demo() {
  if [ "$RESTORE" -eq 1 ]; then
    echo "ROLLBACK: restoring previous working MCP demo"
    "$DOCKER" rm -f "$NEW" >/dev/null 2>&1 || true
    "$DOCKER" start "$OLD" >/dev/null 2>&1 || true
  fi
}
trap restore_demo EXIT HUP INT TERM
if ! "$DOCKER" run -d \
  --name "$NEW" --restart unless-stopped --network host \
  --user 65532:65532 --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 256m --cpus 0.5 --pids-limit 64 \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --mount "type=bind,src=$KEY,dst=/run/secrets/control_plane_api_key,readonly" \
  -e "CONTROL_PLANE_TUNNEL_ID=$TUNNEL_ID" \
  -e "MCP_SERVER_URL=http://127.0.0.1:18767/mcp" \
  -e "LOG_LEVEL=info" \
  -e "LOG_FORMAT=json" \
  "$IMAGE" --control-plane.api-key=file:/run/secrets/control_plane_api_key \
  --health.listen-addr=127.0.0.1:18087 >/dev/null; then
    echo "NEW TUNNEL LAUNCH FAILED"; exit 1
fi
n=0
while [ "$n" -lt 15 ]; do
  if curl -fsS --max-time 4 "http://127.0.0.1:18087/readyz" >/dev/null 2>&1; then
    RESTORE=0
    trap - EXIT HUP INT TERM
    echo "RG_TELEGRAM_TUNNEL_READONLY: READY"
    echo "Production bot/hub, YouTube and Auto Edit remain unchanged."
    echo "Only 4 Telegram diagnostic MCP tools are exposed."
    exit 0
  fi
  n=$((n+1))
  sleep 2
done
echo "NEW TUNNEL NOT READY after 30s; examine its local logs. Reverting."
exit 1
