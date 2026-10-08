#!/bin/sh
# RG NAS: isolated official OpenAI Secure MCP Tunnel smoke test.
# This script DOES NOT connect ChatGPT to the production RG NAS MCP hub.
# It exposes only tunnel-client's embedded safe demo tools (echo, uppercase, server_info).
set -eu

IMAGE="ghcr.io/openai/tunnel-client:v0.0.16"
CONTAINER="rg-openai-tunnel-demo"
ROOT="/volume1/docker/RG_NAS_MCP/OPENAI_TUNNEL"
KEY_FILE="$ROOT/runtime_key"
HEALTH_PORT="18087"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root using sudo sh; no changes made." >&2
  exit 1
fi

case "$(uname -m)" in
  x86_64|aarch64) ;;
  *) echo "Unsupported/unchecked NAS architecture: $(uname -m). No changes made." >&2; exit 1 ;;
esac

# Synology sudo sh does not always include Container Manager binaries on PATH.
DOCKER_BIN=""
for candidate in /usr/local/bin/docker /usr/bin/docker /bin/docker /var/packages/ContainerManager/target/usr/bin/docker /var/packages/ContainerManager/target/bin/docker /var/packages/Docker/target/usr/bin/docker /var/packages/Docker/target/bin/docker; do
  if [ -x "$candidate" ]; then DOCKER_BIN="$candidate"; break; fi
done
if [ -z "$DOCKER_BIN" ] && command -v docker >/dev/null 2>&1; then
  DOCKER_BIN="$(command -v docker)"
fi
if [ -z "$DOCKER_BIN" ]; then
  echo "Could not locate Synology Container Manager Docker CLI. Nothing changed." >&2
  exit 1
fi
export PATH="$(dirname "$DOCKER_BIN"):/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
echo "Docker CLI found: $DOCKER_BIN"
if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  echo "Docker daemon not accessible. Nothing changed." >&2
  exit 1
fi

if "$DOCKER_BIN" container inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "The test container already exists. Refusing to change it."
  "$DOCKER_BIN" inspect -f 'status={{.State.Status}}' "$CONTAINER"
  exit 0
fi

if [ -e "$KEY_FILE" ]; then
  echo "Runtime key file already exists. Refusing to overwrite it." >&2
  exit 1
fi

if ! [ -r /dev/tty ]; then
  echo "No interactive TTY. Use ssh -tt to connect; no changes made." >&2
  exit 1
fi

if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -Eq "[:.]$HEALTH_PORT[[:space:]]"; then
  echo "Health port $HEALTH_PORT is already in use; no changes made." >&2
  exit 1
fi

echo "Preparing pinned official tunnel-client image ($IMAGE) ..."
"$DOCKER_BIN" pull "$IMAGE"

printf '\nPaste your tunnel_... ID from OpenAI Platform (NOT your API key): ' >/dev/tty
IFS= read -r TUNNEL_ID </dev/tty
if ! printf '%s' "$TUNNEL_ID" | grep -Eq '^tunnel_([a-z0-9]{4}_)?[a-z0-9]{32}$'; then
  echo "Invalid tunnel ID; no secrets saved." >&2
  exit 1
fi

echo "Runtime API key input is hidden. Do not paste it into ChatGPT." >/dev/tty
printf 'Paste the restricted Tunnels Read + Use API key: ' >/dev/tty
oldstty="$(stty -g </dev/tty)"
trap 'stty "$oldstty" </dev/tty 2>/dev/null || true' EXIT HUP INT TERM
stty -echo </dev/tty
IFS= read -r API_KEY </dev/tty
stty "$oldstty" </dev/tty
trap - EXIT HUP INT TERM
printf '\n' >/dev/tty

case "$API_KEY" in
  sk-????????????????*) ;;
  *) echo "Key format looks invalid. Nothing saved." >&2; unset API_KEY; exit 1 ;;
esac

umask 077
mkdir -p "$ROOT"
chmod 700 "$ROOT"
printf '%s' "$API_KEY" > "$KEY_FILE.tmp"
unset API_KEY
chown 65532:65532 "$KEY_FILE.tmp"
chmod 400 "$KEY_FILE.tmp"
mv "$KEY_FILE.tmp" "$KEY_FILE"

echo "Launching isolated tunnel test. No RG bot containers will be touched."
if ! "$DOCKER_BIN" run -d \
  --name "$CONTAINER" \
  --network host \
  --user 65532:65532 \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --mount "type=bind,src=$KEY_FILE,dst=/run/secrets/control_plane_api_key,readonly" \
  -e "CONTROL_PLANE_TUNNEL_ID=$TUNNEL_ID" \
  -e "LOG_LEVEL=info" \
  -e "LOG_FORMAT=json" \
  "$IMAGE" \
  --embedded-stateless-mcp-stub \
  --control-plane.api-key=file:/run/secrets/control_plane_api_key \
  --health.listen-addr="127.0.0.1:$HEALTH_PORT"; then
    echo "Tunnel container failed to start. Inspect local Docker logs. No production services changed." >&2
    exit 1
fi

echo "Waiting up to 20 seconds for the tunnel readiness endpoint..."
n=0
while [ "$n" -lt 10 ]; do
  if curl -fsS --max-time 2 "http://127.0.0.1:$HEALTH_PORT/readyz" >/dev/null 2>&1; then
    echo "RG_OPENAI_TUNNEL_DEMO: READY"
    echo "Status: only embedded echo/uppercase/server_info tools; production hub UNTOUCHED."
    echo "No public ports were opened. No existing MCP or bot containers were restarted."
    exit 0
  fi
  n=$((n+1))
  sleep 2
done

echo "RG_OPENAI_TUNNEL_DEMO: STARTED_BUT_NOT_READY"
echo "Share only sanitized status, NEVER the runtime API key:"
echo "  sudo docker ps --filter name=rg-openai-tunnel-demo"
echo "  curl -sS --max-time 5 http://127.0.0.1:$HEALTH_PORT/readyz"
exit 0
