#!/bin/sh
# RG Telegram free Cron Trigger audit & fail-closed repair.
# Does not deploy Worker code, restart services, or publish Telegram messages.
set -eu
ROOT="/volume1/docker"
STATE="$ROOT/RG_NAS_STATE"
ENV_FILE="$ROOT/RG_ALERTS_DEPLOY/deploy.env"
WRANGLER="$ROOT/RG_ALERTS_DEPLOY/cloudflare-alerts/wrangler.toml"
SCRIPT_NAME="rasha-goodbye-air-alerts"
MODE="${1:-audit}"
case "$MODE" in audit|repair) ;; *) echo "ERROR: audit or repair only" >&2; exit 2 ;; esac
[ "$(id -u)" = "0" ] || { echo "ERROR: sudo required" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || exit 2
command -v curl >/dev/null 2>&1 || exit 2
[ -s "$ENV_FILE" ] && [ -s "$WRANGLER" ] || { echo "ERROR: Cloudflare config absent" >&2; exit 2; }
mkdir -p "$STATE"
umask 077
TMP="$(mktemp -d "$STATE/.cron-repair.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
TOKEN="$(sed -n 's/^CLOUDFLARE_API_TOKEN=//p' "$ENV_FILE" | tail -n1 | tr -d '\r\n"' || true)"
[ -n "$TOKEN" ] || TOKEN="$(sed -n 's/^CF_API_TOKEN=//p' "$ENV_FILE" | tail -n1 | tr -d '\r\n"' || true)"
[ -n "$TOKEN" ] || { echo "ERROR: Cloudflare token absent in existing NAS env" >&2; exit 3; }
ACCOUNT="$(sed -n 's/^account_id[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$WRANGLER" | head -n1)"
case "$ACCOUNT" in ""|*[!A-Za-z0-9]*) echo "ERROR: account ID invalid" >&2; exit 2 ;; esac
printf 'connect-timeout = 10\nmax-time = 25\nheader = "Authorization: Bearer %s"\n' "$TOKEN" > "$TMP/curl.conf"
unset TOKEN
URL="https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/workers/scripts/$SCRIPT_NAME/schedules"
fetch_schedule() {
  HTTP="$(curl -sS -L --config "$TMP/curl.conf" -H "Accept: application/json" -o "$TMP/schedules.json" -w '%{http_code}' "$URL" || true)"
  [ "$HTTP" = "200" ] || { echo "ERROR: Cloudflare schedule API HTTP $HTTP; no changes" >&2; exit 4; }
  python3 - "$TMP/schedules.json" > "$TMP/cron-list.json" <<'PY'
import json,sys
try:
    x=json.load(open(sys.argv[1],encoding='utf-8'))
    assert x.get('success') is True
    rows=x['result']['schedules']
    assert isinstance(rows,list) and len(rows)<=25
    crons=[row['cron'] for row in rows]
    assert all(isinstance(c,str) and len(c)<100 for c in crons)
except (OSError,ValueError,KeyError,TypeError,AssertionError):
    raise SystemExit("ERROR: unexpected cron API data, refusing update")
print(json.dumps(crons))
PY
}
fetch_schedule
echo "CLOUDFLARE_ALERTS_CRONS=$(cat "$TMP/cron-list.json")"
echo "NAS_DEPLOY_STATUS=$(cat "$STATE/last_deploy_status" 2>/dev/null || echo missing)"
echo "NAS_DEPLOY_STAGE=$(cat "$STATE/deploy_stage" 2>/dev/null || echo missing)"
if [ -s "$STATE/cloudflare_quota_resume_epoch" ]; then
  python3 - "$STATE/cloudflare_quota_resume_epoch" <<'PY'
import datetime,sys
try:
    epoch=int(open(sys.argv[1]).read().strip())
    print('NAS_QUOTA_COOLDOWN_UNTIL_UTC='+datetime.datetime.fromtimestamp(epoch,datetime.timezone.utc).isoformat())
except (OSError,ValueError,OverflowError): print("NAS_QUOTA_COOLDOWN_INVALID")
PY
fi
if python3 - "$TMP/cron-list.json" <<'PY'
import json,sys
sys.exit(0 if "* * * * *" in json.load(open(sys.argv[1])) else 1)
PY
then
  echo "CRON_TRIGGER_STATUS: PRESENT"
  echo "RESULT: cron exists; investigate scheduled runtime, not redeploy."
  exit 0
fi
echo "CRON_TRIGGER_STATUS: MISSING"
if [ "$MODE" = "audit" ]; then
  echo "RESULT: audit only, no changes"
  exit 1
fi
python3 - "$TMP/cron-list.json" > "$TMP/desired.json" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1],encoding='utf-8'))
if len(rows)>=5: raise SystemExit("ERROR: maximum cron schedules; no change")
rows.append("* * * * *")
print(json.dumps([{"cron":c} for c in rows]))
PY
HTTP="$(curl -sS -L --config "$TMP/curl.conf" -X PUT -H "Content-Type: application/json" --data-binary @"$TMP/desired.json" -o "$TMP/update.json" -w '%{http_code}' "$URL" || true)"
[ "$HTTP" = "200" ] || { echo "ERROR: Cloudflare cron update HTTP $HTTP" >&2; exit 5; }
python3 - "$TMP/update.json" <<'PY'
import json,sys
if json.load(open(sys.argv[1],encoding='utf-8')).get('success') is not True:
    raise SystemExit("ERROR: Cloudflare rejected schedule")
PY
fetch_schedule
python3 - "$TMP/cron-list.json" <<'PY'
import json,sys
if "* * * * *" not in json.load(open(sys.argv[1],encoding='utf-8')):
    raise SystemExit("ERROR: cron not verified after update")
PY
echo "RG_ALERTS_CRON_RESTORED: VERIFIED"
echo "No Telegram sends; Cloudflare cron propagation is asynchronous."
