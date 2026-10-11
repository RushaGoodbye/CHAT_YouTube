#!/bin/sh
# One-time RG Telegram NAS autodeploy script repair. No Worker restarts.
# Source is private, fetched with the existing on-NAS GitHub token and pinned
# to the precise reviewed Git blob SHA. No credentials leave the NAS console.
set -eu

ROOT="/volume1/docker"
TARGET="$ROOT/RG_NAS_AUTO_DEPLOY.sh"
TOKEN_FILE="$ROOT/RG_SECRETS/github_token"
STATE="$ROOT/RG_NAS_STATE"
SOURCE_COMMIT="ed9511aa90be67e150a86d9ad7f2acc32f470f7b"
EXPECTED_BLOB="55e203349d00004821b1f8a5b5e9922ed5cce634"
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
trap 'rm -f "$AUTH_CFG" "$TMP"' EXIT HUP INT TERM
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
if cmp -s "$TMP" "$TARGET"; then
  echo "RG_TELEGRAM_NAS_DEPLOY_SCRIPT_ALREADY_CURRENT"
  exit 0
fi
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$STATE/RG_NAS_AUTO_DEPLOY_pre_r10_repair_$STAMP.sh"
cp -p "$TARGET" "$BACKUP"
chmod 755 "$TMP"
mv -f "$TMP" "$TARGET"
printf '%s\n' "$BACKUP" > "$STATE/rg_nas_auto_deploy_pre_r10_repair_backup"
echo "RG_TELEGRAM_NAS_DEPLOY_SCRIPT_UPDATED: OK"
echo "SOURCE_COMMIT: $SOURCE_COMMIT"
echo "BACKUP: $BACKUP"
echo "Next Synology scheduler tick uses repaired script. Workers and Telegram queues were not touched."
