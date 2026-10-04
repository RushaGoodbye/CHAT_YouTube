#!/bin/sh
set -eu

ROOT="/volume1/docker"
STATE="$ROOT/RG_NAS_STATE"
CONTROL="$ROOT/RG_NAS_CONTROL.sh"
TOKEN_FILE="$ROOT/RG_SECRETS/github_token"
REPO="RushaGoodbye/rasha-goodbye-news-bot"
BRANCH="nas-control"
COMMAND_PATH="nas-control/command.json"
API="https://api.github.com/repos/$REPO"
CURL_CFG="$STATE/.nas-command-bus-curl.conf"
LAST_ID_FILE="$STATE/nas_command_bus_last_id"
AUDIT_FILE="$STATE/nas-command-bus.log"

mkdir -p "$STATE"
[ -s "$TOKEN_FILE" ] || exit 0
TOKEN="$(tr -d '\r\n ' < "$TOKEN_FILE")"
umask 077
printf 'connect-timeout = 10\nmax-time = 30\nheader = "Authorization: Bearer %s"\nheader = "User-Agent: RG-NAS-Command-Bus/1.0"\n' "$TOKEN" > "$CURL_CFG"
trap 'rm -f "$CURL_CFG" "$STATE/.nas-command-bus-command.$$" "$STATE/.nas-command-bus-result.$$" 2>/dev/null || true' EXIT INT TERM

CMD_FILE="$STATE/.nas-command-bus-command.$$"
if ! curl -fsSL --config "$CURL_CFG" -H "Accept: application/vnd.github.raw+json" "$API/contents/$COMMAND_PATH?ref=$BRANCH" -o "$CMD_FILE"; then
  exit 0
fi

META="$(python3 - "$CMD_FILE" <<'PY'
import json,re,sys
try:
    d=json.load(open(sys.argv[1],encoding="utf-8"))
except Exception:
    print("INVALID\t\t\t")
    raise SystemExit
cid=str(d.get("id") or "").strip()
action=str(d.get("action") or "").strip()
args=d.get("args") if isinstance(d.get("args"),dict) else {}
if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}",cid):
    print("INVALID\t\t\t")
    raise SystemExit
print(cid+"\t"+action+"\t"+json.dumps(args,separators=(",",":")))
PY
)"
ID="$(printf '%s' "$META" | cut -f1)"
ACTION="$(printf '%s' "$META" | cut -f2)"
ARGS_JSON="$(printf '%s' "$META" | cut -f3-)"
[ "$ID" != "INVALID" ] || exit 0
LAST_ID="$(cat "$LAST_ID_FILE" 2>/dev/null || true)"
[ "$ID" != "$LAST_ID" ] || exit 0

RESULT_TMP="$STATE/.nas-command-bus-result.$$"
STATUS="ok"
RC=0

run_control() {
  "$CONTROL" "$@"
}

case "$ACTION" in
  noop)
    printf '%s\n' "noop"
    ;;
  status|health|doctor|queues|sources|alerts|content|calendar|ai-budget|bot-status|cloud-health)
    run_control "$ACTION"
    ;;
  deploy)
    run_control deploy
    ;;
  force-deploy)
    run_control force-deploy
    ;;
  selftest)
    "$ROOT/RG_NAS_DAILY_SELFTEST.sh"
    ;;
  docker-status)
    docker ps -a --format '{{.Names}}\t{{.Status}}' | grep '^rg-' || true
    ;;
  executor-status)
    docker inspect -f 'name={{.Name}} running={{.State.Running}} status={{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}}' rg-nas-autodeploy 2>/dev/null || {
      printf '%s\n' "rg-nas-autodeploy missing"
      exit 1
    }
    ;;
  executor-restart)
    docker restart rg-nas-autodeploy
    docker inspect -f 'running={{.State.Running}} status={{.State.Status}}' rg-nas-autodeploy
    ;;
  mcp-deploy)
    MCP_DIR="/volume1/RG_AUTO_EDIT/REMOTE_MCP/SOURCE"
    [ -f "$MCP_DIR/docker-compose.yml" ] || {
      printf '%s\n' "RG NAS MCP compose missing: $MCP_DIR/docker-compose.yml"
      exit 1
    }
    [ -f "$MCP_DIR/Dockerfile" ] || {
      printf '%s\n' "RG NAS MCP hub Dockerfile missing"
      exit 1
    }
    [ -f "$MCP_DIR/Dockerfile.worker" ] || {
      printf '%s\n' "RG NAS MCP worker Dockerfile missing"
      exit 1
    }
    if docker compose version >/dev/null 2>&1; then
      docker compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" up -d --build
      docker compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" ps
    elif command -v docker-compose >/dev/null 2>&1; then
      docker-compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" up -d --build
      docker-compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" ps
    else
      printf '%s\n' "Docker Compose is unavailable"
      exit 1
    fi
    ;;
  mcp-status)
    for NAME in rg-nas-mcp-hub rg-mcp-youtube rg-mcp-telegram rg-mcp-auto-edit; do
      if docker inspect "$NAME" >/dev/null 2>&1; then
        docker inspect -f 'name={{.Name}} running={{.State.Running}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}} restart={{.HostConfig.RestartPolicy.Name}}' "$NAME"
      else
        printf 'name=%s status=missing\n' "$NAME"
      fi
    done
    ;;
  disk)
    df -h "$ROOT" /volume1 2>/dev/null | awk 'NR==1 || !seen[$1]++'
    ;;
  baseline)
    cat "$STATE/production_baseline.json" 2>/dev/null || printf '%s\n' '{}'
    ;;
  logs)
    LOG_NAME="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(str(d.get("name","auto")))' "$ARGS_JSON")"
    LINES="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); n=int(d.get("lines",80)); print(max(1,min(200,n)))' "$ARGS_JSON" 2>/dev/null || echo 80)"
    case "$LOG_NAME" in auto|video|alerts|content|selftest|youtube) ;; *) LOG_NAME="auto" ;; esac
    run_control logs "$LOG_NAME" "$LINES"
    ;;
  *)
    STATUS="rejected"
    RC=2
    printf 'Action not allowlisted: %s\n' "$ACTION"
    ;;
esac >"$RESULT_TMP" 2>&1 || {
  RC=$?
  [ "$STATUS" = "rejected" ] || STATUS="error"
}

FINISHED="$(date -Iseconds)"
RESULT_PATH="nas-control/results/$ID.json"
PAYLOAD="$(python3 - "$ID" "$ACTION" "$STATUS" "$RC" "$FINISHED" "$RESULT_TMP" <<'PY'
import base64,json,sys
cid,action,status,rc,finished,path=sys.argv[1:]
try:
    out=open(path,encoding="utf-8",errors="replace").read()
except Exception:
    out=""
out=out[-12000:]
doc={"version":1,"id":cid,"action":action,"status":status,"exitCode":int(rc),"finishedAt":finished,"output":out}
content=base64.b64encode((json.dumps(doc,ensure_ascii=False,indent=2)+"\n").encode()).decode()
print(json.dumps({"message":f"NAS command result {cid}","content":content,"branch":"nas-control"},ensure_ascii=False))
PY
)"

HTTP="$(curl -sS --config "$CURL_CFG" -o "$STATE/.nas-command-bus-upload.$$" -w '%{http_code}' -X PUT   -H "Accept: application/vnd.github+json" -H "Content-Type: application/json"   --data "$PAYLOAD" "$API/contents/$RESULT_PATH" || true)"
if [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ]; then
  printf '%s\n' "$ID" > "$LAST_ID_FILE"
  printf '%s id=%s action=%s status=%s rc=%s\n' "$FINISHED" "$ID" "$ACTION" "$STATUS" "$RC" >> "$AUDIT_FILE"
  tail -n 500 "$AUDIT_FILE" > "$AUDIT_FILE.tmp" 2>/dev/null || true
  [ -s "$AUDIT_FILE.tmp" ] && mv -f "$AUDIT_FILE.tmp" "$AUDIT_FILE" || rm -f "$AUDIT_FILE.tmp"
fi
rm -f "$STATE/.nas-command-bus-upload.$$" 2>/dev/null || true
