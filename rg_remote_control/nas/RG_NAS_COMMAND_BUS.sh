#!/bin/sh
set -eu

ROOT="/volume1/docker"
STATE="$ROOT/RG_NAS_STATE"
CONTROL="$ROOT/RG_NAS_CONTROL.sh"
TOKEN_FILE="$ROOT/RG_SECRETS/github_token"
REPO="RushaGoodbye/rasha-goodbye-news-bot"
BRANCH="nas-control"
COMMAND_PATH="nas-control/telegram/command.json"
API="https://api.github.com/repos/$REPO"
CURL_CFG="$STATE/.nas-command-bus-curl.$"
LAST_ID_FILE="$STATE/telegram_command_bus_last_id"
AUDIT_FILE="$STATE/telegram-command-bus.log"
ADMIN_URL_FILE="$ROOT/RG_NAS_CONTROL/admin_url"
ADMIN_TOKEN_FILE="$ROOT/RG_SECRETS/rg_admin_token"
LOCK_DIR="$STATE/telegram-command-bus.lock"
LOCK_STALE_SECONDS=300

mkdir -p "$STATE"

acquire_bus_lock() {
  NOW_EPOCH="$(date +%s)"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$NOW_EPOCH" > "$LOCK_DIR/started_at"
    printf '%s\n' "$(date -Iseconds)" > "$STATE/telegram_command_bus_lock_at"
    return 0
  fi
  STARTED="$(cat "$LOCK_DIR/started_at" 2>/dev/null || echo 0)"
  case "$STARTED" in ''|*[!0-9]*) STARTED=0 ;; esac
  AGE=$((NOW_EPOCH - STARTED))
  if [ "$STARTED" -gt 0 ] 2>/dev/null && [ "$AGE" -ge "$LOCK_STALE_SECONDS" ] 2>/dev/null; then
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" || return 1
    printf '%s\n' "$NOW_EPOCH" > "$LOCK_DIR/started_at"
    printf '%s\n' "$(date -Iseconds)" > "$STATE/telegram_command_bus_lock_at"
    printf '%s\n' "stale_lock_recovered" > "$STATE/telegram_command_bus_lock_recovery"
    return 0
  fi
  printf '%s\n' "$(date -Iseconds)" > "$STATE/telegram_command_bus_lock_busy_at"
  return 1
}

report_bus_health() {
  STATUS_VALUE="$1"
  PHASE_VALUE="$2"
  COMMAND_ID_VALUE="${3:-}"
  ACTION_VALUE="${4:-}"
  RESULT_STATUS_VALUE="${5:-}"
  GITHUB_HTTP_VALUE="${6:-0}"
  ADMIN_HTTP_VALUE="${7:-0}"
  ERROR_VALUE="${8:-}"
  [ -s "$ADMIN_URL_FILE" ] || return 0
  [ -s "$ADMIN_TOKEN_FILE" ] || return 0
  ADMIN_URL_VALUE="$(cat "$ADMIN_URL_FILE")"
  ADMIN_TOKEN_VALUE="$(tr -d '\r\n ' < "$ADMIN_TOKEN_FILE")"
  PAYLOAD_FILE="$STATE/.nas-command-bus-health.$"
  python3 - "$STATUS_VALUE" "$PHASE_VALUE" "$COMMAND_ID_VALUE" "$ACTION_VALUE" "$RESULT_STATUS_VALUE" "$GITHUB_HTTP_VALUE" "$ADMIN_HTTP_VALUE" "$ERROR_VALUE" > "$PAYLOAD_FILE" <<'PY'
import json,sys,datetime
status,phase,cid,action,result_status,github_http,admin_http,error=sys.argv[1:]
print(json.dumps({
  "checkedAt":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "status":status,
  "phase":phase,
  "commandId":cid,
  "action":action,
  "resultStatus":result_status,
  "githubHttp":int(github_http or 0),
  "adminHttp":int(admin_http or 0),
  "error":error[:240],
},ensure_ascii=False))
PY
  curl -fsS --connect-timeout 10 --max-time 20     -H "Authorization: Bearer $ADMIN_TOKEN_VALUE"     -H "Content-Type: application/json"     --data-binary @"$PAYLOAD_FILE"     "$ADMIN_URL_VALUE/actions/nas-command-bus-health" >/dev/null 2>&1 || true
  rm -f "$PAYLOAD_FILE" 2>/dev/null || true
  return 0
}

acquire_bus_lock || exit 0
[ -s "$TOKEN_FILE" ] || { report_bus_health "ERROR" "token_missing" "" "" "" 0 0 "github_token_missing"; exit 0; }
TOKEN="$(tr -d '\r\n ' < "$TOKEN_FILE")"
umask 077
printf 'connect-timeout = 10\nmax-time = 30\nheader = "Authorization: Bearer %s"\nheader = "User-Agent: RG-NAS-Command-Bus/1.0"\n' "$TOKEN" > "$CURL_CFG"
trap 'rm -rf "$LOCK_DIR"; rm -f "$CURL_CFG" "$STATE/.nas-command-bus-command.$" "$STATE/.nas-command-bus-result.$" "$STATE/.nas-command-bus-health.$" 2>/dev/null || true' EXIT INT TERM

CMD_FILE="$STATE/.nas-command-bus-command.$$"
if ! curl -fsSL --config "$CURL_CFG" -H "Accept: application/vnd.github.raw+json" "$API/contents/$COMMAND_PATH?ref=$BRANCH" -o "$CMD_FILE"; then
  report_bus_health "ERROR" "command_fetch_failed" "" "" "" 0 0 "github_command_fetch_failed"
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
[ "$ID" != "INVALID" ] || { report_bus_health "ERROR" "command_invalid" "" "" "" 0 0 "invalid_command_json"; exit 0; }
printf '%s\n' "$ID" > "$STATE/telegram_command_bus_seen_id"
printf '%s\n' "$ACTION" > "$STATE/telegram_command_bus_seen_action"
printf '%s\n' "$(date -Iseconds)" > "$STATE/telegram_command_bus_seen_at"
LAST_ID="$(cat "$LAST_ID_FILE" 2>/dev/null || true)"
if [ "$ID" = "$LAST_ID" ]; then
  report_bus_health "OK" "idle_already_processed" "$ID" "$ACTION" "already_processed" 0 0 ""
  exit 0
fi
printf '%s\n' "executing" > "$STATE/telegram_command_bus_phase"
printf '%s\n' "$ID" > "$STATE/telegram_command_bus_active_id"
printf '%s\n' "$ACTION" > "$STATE/telegram_command_bus_active_action"
printf '%s\n' "$(date -Iseconds)" > "$STATE/telegram_command_bus_phase_at"
report_bus_health "RUNNING" "executing" "$ID" "$ACTION" "" 0 0 ""

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
  status|health|doctor|queues|sources|alerts|content|calendar|ai-budget|bot-status|cloud-health|telegram-control-plane|telegram-sync)
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
  telegram-mcp-control-plane-mount)
    MCP_DIR="/volume1/docker/RG_NAS_MCP/SOURCE"
    COMPOSE="$MCP_DIR/docker-compose.yml"
    [ -f "$COMPOSE" ] || { printf '%s\n' "RG NAS MCP compose missing: $COMPOSE"; exit 1; }
    mkdir -p /volume1/docker/RG_TELEGRAM
    python3 - "$COMPOSE" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1])
text=p.read_text(encoding="utf-8")
mount="      - /volume1/docker/RG_TELEGRAM:/workspace/rg_telegram:rw\n"
if mount in text:
    print("RG_TELEGRAM mount already present")
    raise SystemExit(0)
start=text.find("  telegram-worker:")
end=text.find("\n  auto-edit-worker:", start)
if start < 0 or end < 0:
    raise SystemExit("telegram-worker block not found")
block=text[start:end]
anchor="      - /volume1/docker/RG_NAS_CONTROL:/workspace/nas_control:rw\n"
if anchor not in block:
    raise SystemExit("telegram-worker nas_control volume anchor missing")
block=block.replace(anchor, anchor+mount, 1)
text=text[:start]+block+text[end:]
tmp=p.with_suffix(".yml.rg.tmp")
tmp.write_text(text,encoding="utf-8")
tmp.replace(p)
print("RG_TELEGRAM mount added")
PY
    if docker compose version >/dev/null 2>&1; then
      docker compose -p rg-nas-mcp -f "$COMPOSE" up -d --build telegram-worker hub
      docker compose -p rg-nas-mcp -f "$COMPOSE" ps telegram-worker hub
    elif command -v docker-compose >/dev/null 2>&1; then
      docker-compose -p rg-nas-mcp -f "$COMPOSE" up -d --build telegram-worker hub
      docker-compose -p rg-nas-mcp -f "$COMPOSE" ps telegram-worker hub
    else
      printf '%s\n' "Docker Compose is unavailable"
      exit 1
    fi
    ;;
  control-app-install)
    sh "$ROOT/RG_TELEGRAM_CONTROL_APP_INSTALL.sh"
    ;;
  control-app-status)
    printf 'status='
    cat "$STATE/rg_telegram_control_app_status" 2>/dev/null || printf 'UNKNOWN'
    printf '\n'
    printf 'deployed_at='
    cat "$STATE/rg_telegram_control_app_deployed_at" 2>/dev/null || true
    printf '\n'
    if command -v curl >/dev/null 2>&1; then
      curl -fsS --max-time 5 http://127.0.0.1:8788/healthz || true
      printf '\n'
    fi
    docker ps -a --format '{{.Names}}\t{{.Status}}' | grep '^rg-telegram-control' || true
    ;;
  telegram-mcp-deploy)
    MCP_DIR="/volume1/docker/RG_NAS_MCP/SOURCE"
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
      docker compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" up -d --build telegram-worker hub
      docker compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" ps hub telegram-worker
    elif command -v docker-compose >/dev/null 2>&1; then
      docker-compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" up -d --build telegram-worker hub
      docker-compose -p rg-nas-mcp -f "$MCP_DIR/docker-compose.yml" ps hub telegram-worker
    else
      printf '%s\n' "Docker Compose is unavailable"
      exit 1
    fi
    ;;
  mcp-status)
    for NAME in rg-nas-mcp-hub rg-mcp-telegram; do
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
  stable-baseline)
    DEPLOY_STATUS="$(cat "$STATE/last_deploy_status" 2>/dev/null || true)"
    DEPLOY_STAGE="$(cat "$STATE/deploy_stage" 2>/dev/null || true)"
    LIVE_STATUS="$(cat "$STATE/live_smoke_status" 2>/dev/null || true)"
    DEPLOYED_SHA="$(cat "$STATE/last_deployed_sha" 2>/dev/null || true)"
    LIVE_SHA="$(cat "$STATE/live_smoke_sha" 2>/dev/null || true)"
    BACKUP="$(cat "$STATE/last_backup" 2>/dev/null || true)"
    [ "$DEPLOY_STATUS" = "OK" ] || { printf '%s\n' "baseline refused: last_deploy_status=$DEPLOY_STATUS"; exit 1; }
    [ "$DEPLOY_STAGE" = "COMPLETE" ] || { printf '%s\n' "baseline refused: deploy_stage=$DEPLOY_STAGE"; exit 1; }
    [ "$LIVE_STATUS" = "OK" ] || { printf '%s\n' "baseline refused: live_smoke_status=$LIVE_STATUS"; exit 1; }
    [ -n "$DEPLOYED_SHA" ] && [ "$DEPLOYED_SHA" = "$LIVE_SHA" ] || {
      printf 'baseline refused: deployed_sha=%s live_sha=%s\n' "$DEPLOYED_SHA" "$LIVE_SHA"
      exit 1
    }
    [ -n "$BACKUP" ] || { printf '%s\n' "baseline refused: backup missing"; exit 1; }
    python3 - "$STATE" "$DEPLOYED_SHA" "$BACKUP" <<'PY'
import json,sys,datetime,pathlib,os
state=pathlib.Path(sys.argv[1])
sha=sys.argv[2]
backup=sys.argv[3]
def read(name):
    p=state/name
    return p.read_text(encoding="utf-8",errors="replace").strip() if p.is_file() else None
required=("video","alerts","content")
if not all(os.path.isdir(os.path.join(backup,name)) for name in required):
    raise SystemExit("baseline refused: backup incomplete")
doc={
    "sha":sha,
    "deployedAt":read("last_deployed_at"),
    "backup":backup,
    "liveSmokeAt":read("live_smoke_checked_at"),
    "videoSha":sha,
    "alertsSha":sha,
    "contentSha":sha,
    "status":"STABLE",
    "telegramContour":"telegram",
    "mcpDeployStatus":read("mcp_deploy_status"),
}
tmp=state/"production_baseline.json.tmp"
tmp.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
tmp.replace(state/"production_baseline.json")
print(json.dumps(doc,ensure_ascii=False,indent=2))
PY
    ;;
  telegram-mcp-call)
    TOOL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(str(d.get("tool","")))' "$ARGS_JSON")"
    TOOL_ARGS_B64="$(python3 -c 'import base64,json,sys; d=json.loads(sys.argv[1]); a=d.get("tool_args") if isinstance(d.get("tool_args"),dict) else {}; print(base64.b64encode(json.dumps(a,separators=(",",":")).encode()).decode())' "$ARGS_JSON")"
    case "$TOOL" in
      telegram_fs_list|telegram_fs_read_text|telegram_fs_write_text|telegram_fs_make_dir|telegram_fs_copy|telegram_command_run) ;;
      *)
        printf 'Telegram MCP tool not allowlisted: %s\n' "$TOOL"
        exit 2
        ;;
    esac
    docker exec -e RG_MCP_TOOL="$TOOL" -e RG_MCP_ARGS_B64="$TOOL_ARGS_B64" rg-nas-mcp-hub python -c '
import asyncio,base64,json,os
from mcp import Client
async def main():
    tool=os.environ["RG_MCP_TOOL"]
    args=json.loads(base64.b64decode(os.environ["RG_MCP_ARGS_B64"]).decode())
    async with Client("http://127.0.0.1:8765/mcp") as client:
        result=await client.call_tool(tool,args)
        out={"tool":tool,"is_error":bool(result.is_error),"structured_content":result.structured_content,"content":[]}
        for item in result.content or []:
            row={"type":getattr(item,"type",None)}
            text=getattr(item,"text",None)
            if text is not None: row["text"]=text
            out["content"].append(row)
        print(json.dumps(out,ensure_ascii=False))
        return 1 if result.is_error else 0
rc=asyncio.run(main())
raise SystemExit(rc)
'
    ;;
  telegram-mcp-smoke)
    docker exec rg-nas-mcp-hub python -m rg_remote_mcp.telegram_smoke
    ;;
  scanner-run)
    run_control scanner-run
    ;;
  telegram-watchdog-run)
    rm -rf "$STATE/telegram-watchdog.lock" 2>/dev/null || true
    sh "$ROOT/RG_NAS_TELEGRAM_WATCHDOG.sh"
    run_control telegram-watchdog
    ;;
  telegram-sync-run)
    run_control telegram-sync
    ;;
  telegram-audit)
    echo "=== MCP TELEGRAM SMOKE ==="
    docker exec rg-nas-mcp-hub python -m rg_remote_mcp.telegram_smoke 2>&1 || true
    echo "=== NAS HEALTH ==="
    run_control health 2>&1 || true
    echo "=== BOT STATUS ==="
    run_control bot-status 2>&1 || true
    echo "=== QUEUES ==="
    run_control queues 2>&1 || true
    echo "=== ALERTS ==="
    run_control alerts 2>&1 || true
    echo "=== CONTENT ==="
    run_control content 2>&1 || true
    echo "=== CALENDAR ==="
    run_control calendar 2>&1 || true
    echo "=== DEPLOY STATE ==="
    for KEY in last_deployed_sha last_deploy_status deploy_stage live_smoke_status live_smoke_sha live_smoke_checked_at last_backup selftest_ok; do
      printf '%s=' "$KEY"
      cat "$STATE/$KEY" 2>/dev/null || true
      printf '\n'
    done
    echo "=== PRODUCTION BASELINE ==="
    cat "$STATE/production_baseline.json" 2>/dev/null || printf '%s\n' '{}'
    echo "=== NAS TELEGRAM WATCHDOG ==="
    printf 'status='
    cat "$STATE/telegram_watchdog_status" 2>/dev/null || true
    printf '\n'
    cat "$STATE/telegram-watchdog-status.json" 2>/dev/null || printf '%s\n' '{}'
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
printf '%s\n' "executed" > "$STATE/telegram_command_bus_phase"
printf '%s\n' "$RC" > "$STATE/telegram_command_bus_rc"
printf '%s\n' "$STATUS" > "$STATE/telegram_command_bus_result_status"
printf '%s\n' "$FINISHED" > "$STATE/telegram_command_bus_phase_at"
RESULT_PATH="nas-control/telegram/results/$ID.json"
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

DELIVERED=0
ADMIN_HTTP=""
if [ -s "$ADMIN_URL_FILE" ] && [ -s "$ADMIN_TOKEN_FILE" ]; then
  ADMIN_URL="$(cat "$ADMIN_URL_FILE")"
  ADMIN_TOKEN="$(tr -d '\r\n ' < "$ADMIN_TOKEN_FILE")"
  ADMIN_CFG="$STATE/.nas-command-bus-admin.$$"
  printf 'connect-timeout = 10\nmax-time = 30\nheader = "Authorization: Bearer %s"\n' "$ADMIN_TOKEN" > "$ADMIN_CFG"
  ADMIN_PAYLOAD="$(python3 - "$ID" "$ACTION" "$STATUS" "$RC" "$FINISHED" "$RESULT_TMP" <<'PY'
import json,sys
cid,action,status,rc,finished,path=sys.argv[1:]
try:
    out=open(path,encoding="utf-8",errors="replace").read()
except Exception:
    out=""
print(json.dumps({"id":cid,"action":action,"status":status,"exitCode":int(rc),"finishedAt":finished,"output":out[-12000:]},ensure_ascii=False))
PY
)"
  ADMIN_HTTP="$(curl -sS --config "$ADMIN_CFG" -o "$STATE/.nas-command-bus-admin-out.$$" -w '%{http_code}' -X POST -H "Content-Type: application/json" --data "$ADMIN_PAYLOAD" "$ADMIN_URL/actions/mcp-result" || true)"
  rm -f "$ADMIN_CFG" "$STATE/.nas-command-bus-admin-out.$$" 2>/dev/null || true
  printf '%s\n' "${ADMIN_HTTP:-0}" > "$STATE/telegram_command_bus_admin_http"
  [ "$ADMIN_HTTP" = "200" ] && DELIVERED=1
fi

HTTP="$(curl -sS --config "$CURL_CFG" -o "$STATE/.nas-command-bus-upload.$$" -w '%{http_code}' -X PUT \
  -H "Accept: application/vnd.github+json" -H "Content-Type: application/json" \
  --data "$PAYLOAD" "$API/contents/$RESULT_PATH" || true)"
printf '%s\n' "${HTTP:-0}" > "$STATE/telegram_command_bus_github_http"
if [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ]; then
  DELIVERED=1
fi

if [ "$DELIVERED" = "1" ]; then
  printf '%s\n' "result_delivered" > "$STATE/telegram_command_bus_phase"
  printf '%s\n' "$(date -Iseconds)" > "$STATE/telegram_command_bus_phase_at"
  report_bus_health "OK" "result_delivered" "$ID" "$ACTION" "$STATUS" "${HTTP:-0}" "${ADMIN_HTTP:-0}" ""
  printf '%s\n' "$ID" > "$LAST_ID_FILE"
  printf '%s id=%s action=%s status=%s rc=%s admin_http=%s github_http=%s\n' "$FINISHED" "$ID" "$ACTION" "$STATUS" "$RC" "${ADMIN_HTTP:-none}" "${HTTP:-none}" >> "$AUDIT_FILE"
  tail -n 500 "$AUDIT_FILE" > "$AUDIT_FILE.tmp" 2>/dev/null || true
  [ -s "$AUDIT_FILE.tmp" ] && mv -f "$AUDIT_FILE.tmp" "$AUDIT_FILE" || rm -f "$AUDIT_FILE.tmp"
else
  printf '%s\n' "result_delivery_failed" > "$STATE/telegram_command_bus_phase"
  printf '%s\n' "$(date -Iseconds)" > "$STATE/telegram_command_bus_phase_at"
  report_bus_health "ERROR" "result_delivery_failed" "$ID" "$ACTION" "$STATUS" "${HTTP:-0}" "${ADMIN_HTTP:-0}" "result_delivery_failed"
  printf '%s id=%s action=%s result_delivery_failed admin_http=%s github_http=%s\n' "$FINISHED" "$ID" "$ACTION" "${ADMIN_HTTP:-none}" "${HTTP:-none}" >> "$AUDIT_FILE"
fi
rm -f "$STATE/.nas-command-bus-upload.$$" 2>/dev/null || true
