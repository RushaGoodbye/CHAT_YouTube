#!/bin/sh
# Lock-aware RG Telegram NAS quota protection + rollback preservation. No Worker restarts.
# Source is private, fetched with the existing on-NAS GitHub token and pinned
# to the precise reviewed Git blob SHA. No credentials leave the NAS console.
set -eu

ROOT="/volume1/docker"
TARGET="$ROOT/RG_NAS_AUTO_DEPLOY.sh"
TOKEN_FILE="$ROOT/RG_SECRETS/github_token"
STATE="$ROOT/RG_NAS_STATE"
SOURCE_COMMIT="59cec016079576c0114d6390fb3ba4c21d3a60cc"
EXPECTED_BLOB="6d963552e5134aa3ef0c61484e8a4e1ce9850fab"
REPO="RushaGoodbye/rasha-goodbye-news-bot"
URL="https://api.github.com/repos/$REPO/contents/nas/RG_NAS_AUTO_DEPLOY.sh?ref=$SOURCE_COMMIT"

[ "$(id -u)" = "0" ] || { echo "ERROR: run with sudo"; exit 1; }
[ -s "$TARGET" ] || { echo "ERROR: NAS deploy script not found"; exit 1; }
[ -s "$TOKEN_FILE" ] || { echo "ERROR: on-NAS private GitHub token not found"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: Python 3 unavailable"; exit 1; }
mkdir -p "$STATE"
umask 077
AUTH_CFG="$(mktemp "$STATE/.rg-github-auth.XXXXXX")"
TMP="$(mktemp "$ROOT/.rg-nas-auto-deploy-update.XXXXXX")"
LOCK_DIR="$STATE/deploy.lock"
LOCK_OWNED=0
cleanup() {
  rm -f "$AUTH_CFG" "$TMP"
  if [ "$LOCK_OWNED" = "1" ]; then
    rm -rf "$LOCK_DIR"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
TOKEN="$(tr -d '\r\n ' < "$TOKEN_FILE")"
printf 'connect-timeout = 10\nmax-time = 60\nheader = "Authorization: Bearer %s"\nheader = "User-Agent: RG-Telegram-NAS-Safe-Bootstrap"\n' "$TOKEN" > "$AUTH_CFG"
unset TOKEN

ATTEMPT=1
SUCCESS=0
while [ "$ATTEMPT" -le 4 ]; do
  HTTP=""
  if HTTP="$(curl -fsSL -L --config "$AUTH_CFG" -H "Accept: application/vnd.github.raw+json" -w '%{http_code}' "$URL" -o "$TMP")"; then
    SUCCESS=1
    break
  fi
  echo "PRIVATE_SOURCE_FETCH_RETRY attempt=$ATTEMPT http=${HTTP:-unknown}"
  if [ "$ATTEMPT" -lt 4 ]; then sleep "$((ATTEMPT * 4))"; fi
  ATTEMPT=$((ATTEMPT + 1))
done
[ "$SUCCESS" = "1" ] || { echo "ERROR: private GitHub source fetch failed after 4 attempts"; exit 1; }

python3 - "$TMP" "$EXPECTED_BLOB" <<'PY'
import hashlib,sys
p,expected=sys.argv[1:]
data=open(p,'rb').read()
digest=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
if digest != expected:
    raise SystemExit('ERROR: GitHub source blob hash mismatch; refusing update')
print('PRIVATE_SOURCE_SHA_VERIFIED:',digest)
PY

sh -n "$TMP" || { echo "ERROR: NAS deploy script shell syntax invalid"; exit 1; }
grep -q 'RG_NAS_ARCHIVE_VALID' "$TMP" || { echo "ERROR: archive retry guard missing"; exit 1; }
grep -q 'deploy_exit_cleanup()' "$TMP" || { echo "ERROR: exit-state guard missing"; exit 1; }
grep -q 'RG_NAS_CLOUDFLARE_DAILY_QUOTA_COOLDOWN' "$TMP" || { echo "ERROR: Cloudflare quota cooldown missing"; exit 1; }
grep -q 'RG_NAS_CLOUDFLARE_QUOTA_EXHAUSTED' "$TMP" || { echo "ERROR: Cloudflare quota error detector missing"; exit 1; }
grep -q 'RG_NAS_ROLLBACK_CONTROL_PLANE_PRESERVED' "$TMP" || { echo "ERROR: rollback preserving control plane missing"; exit 1; }
grep -q 'CONTROL_PLANE_TOUCHED=1' "$TMP" || { echo "ERROR: rollback control-plane partial-install recovery missing"; exit 1; }
# The old in-flight installer unconditionally restored the control-plane
# backup on failed Worker smoke. Acquire exactly the same NAS deploy.lock
# BEFORE installing so no running rollback can erase this safety fix.
COUNT=0
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
  COUNT=$((COUNT + 1))
  if [ "$COUNT" -ge 180 ]; then
    echo "ERROR: NAS deployment lock remained busy; no changes made"
    exit 2
  fi
  if [ "$((COUNT % 5))" = "1" ]; then
    echo "RG_TELEGRAM_QUOTA_GUARD_WAITING_FOR_DEPLOY_LOCK"
  fi
  sleep 4
done
LOCK_OWNED=1
printf '%s\n' "$" > "$LOCK_DIR/pid"
date +%s > "$LOCK_DIR/started_at"

if cmp -s "$TMP" "$TARGET"; then
  echo "RG_TELEGRAM_NAS_DEPLOY_SCRIPT_ALREADY_CURRENT"
else
  STAMP="$(date +%Y%m%d_%H%M%S)"
  BACKUP="$STATE/RG_NAS_AUTO_DEPLOY_pre_quota_rollback_fix_$STAMP.sh"
  cp -p "$TARGET" "$BACKUP"
  chmod 755 "$TMP"
  mv -f "$TMP" "$TARGET"
  printf '%s\n' "$BACKUP" > "$STATE/rg_nas_quota_rollback_fix_backup"
  echo "RG_TELEGRAM_NAS_DEPLOY_SCRIPT_UPDATED: OK"
  echo "SOURCE_COMMIT: $SOURCE_COMMIT"
  echo "BACKUP: $BACKUP"
fi

# A fresh Cloudflare quota error from the actual NAS smoke is enough to pause
# redundant deploys. Fail safe: never infer quotas from a stale/invalid file.
if python3 - "$STATE/last-live-smoke.json" <<'PY'
import json,sys,datetime
try:
    data=json.load(open(sys.argv[1],encoding='utf-8'))
    at=datetime.datetime.fromisoformat(data['checkedAt'].replace('Z','+00:00'))
    age=(datetime.datetime.now(datetime.timezone.utc)-at).total_seconds()
    checks=json.dumps(data.get('checks',[]),ensure_ascii=False)
    assert 0 <= age <= 7200
    assert 'Exceeded allowed volume of requests in Durable Objects free tier' in checks or 'KV get() limit exceeded for the day' in checks
except (OSError,ValueError,KeyError,AssertionError,TypeError):
    sys.exit(1)
PY
then
  NOW_EPOCH="$(date -u +%s)"
  NEXT_RESET=$(( ((NOW_EPOCH / 86400) + 1) * 86400 + 300 ))
  printf '%s\n' "$NEXT_RESET" > "$STATE/cloudflare_quota_resume_epoch"
  printf '%s\n' "DO_OR_KV_FREE_DAILY_LIMIT" > "$STATE/cloudflare_quota_reason"
  printf '%s\n' "$(date -Iseconds)" > "$STATE/cloudflare_quota_detected_at"
  echo "RG_CLOUDFLARE_QUOTA_COOLDOWN_SET until_utc_epoch=$NEXT_RESET"
else
  echo "RG_CLOUDFLARE_QUOTA_COOLDOWN_NOT_SET: no recent quota proof"
fi
echo "RG_TELEGRAM_NAS_PROTECTIVE_UPDATE_OK"
echo "Existing Cloudflare Workers, Telegram queues, YouTube and Auto Edit were not touched."
exit 0

