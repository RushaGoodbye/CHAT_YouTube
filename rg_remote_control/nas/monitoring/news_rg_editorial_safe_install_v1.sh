#!/bin/sh
# NEWS RG editorial source/rewriter safe install: no runtime cutover.
# Installs only NEW filename modules; never edits existing live bot/poller,
# database, callback, scheduler, Cloudflare or public Telegram settings.
set -eu
umask 077
if [ "$(id -u)" -ne 0 ]; then
  echo NEWS_RG_EDITORIAL_ROOT_REQUIRED
  exit 2
fi
ROOT='/volume1/docker/RG_TELEGRAM_NEWS_2'
TARGET="$ROOT/operator"
STAGE='/tmp/news_rg_editorial_safe_install_v1'
VAULT='/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots'
SRC='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/3d40142ea4f660f68194e012692252617dc70a70/rg_remote_control/nas/monitoring'
case "$TARGET" in
  /volume1/docker/RG_TELEGRAM_NEWS_2/operator) : ;;
  *) echo NEWS_RG_TARGET_INVALID; exit 2 ;;
esac
for p in "$ROOT" "$TARGET" "$VAULT"; do
  if [ ! -d "$p" ] || [ -L "$p" ]; then
    echo NEWS_RG_EXPECTED_DIRECTORY_INVALID
    exit 2
  fi
done
if [ -L "$STAGE" ]; then
  echo NEWS_RG_STAGE_SYMLINK_REFUSED
  exit 2
fi
mkdir -p "$STAGE"
chmod 700 "$STAGE"
MODULES='news_rg_editorial_contract_v1.py
news_rg_source_shadow_ingest_v1.py
news_rg_editorial_rewrite_shadow_v1.py
news_rg_preflight_v1.py
news_rg_moderator_route_probe_v1.py'
for name in $MODULES; do
  if [ -L "$STAGE/$name" ] || [ -L "$TARGET/$name" ]; then
    echo NEWS_RG_MODULE_SYMLINK_REFUSED
    exit 2
  fi
  curl -fsSL --connect-timeout 10 --max-time 45 "$SRC/$name" -o "$STAGE/$name"
  chmod 600 "$STAGE/$name"
  /usr/bin/python3 -m py_compile "$STAGE/$name"
done
# Tests never consume provider quota or use Bot API.
for name in $MODULES; do
  /usr/bin/python3 "$STAGE/$name" selftest
done
# Existing code is never overwritten silently; if a file is already present,
# stop. This prevents an accidental uncontrolled rollback/cutover.
for name in $MODULES; do
  if [ -e "$TARGET/$name" ]; then
    echo NEWS_RG_EXISTING_MODULE_PRESERVED_INSTALL_ABORTED
    exit 3
  fi
done
# No installed source/bot/poller/DSM task/config file is changed.
for name in $MODULES; do
  cp "$STAGE/$name" "$TARGET/$name"
  chmod 600 "$TARGET/$name"
done
echo NEWS_RG_EDITORIAL_MODULES_INSTALLED_NOT_ACTIVATED
/usr/bin/python3 "$TARGET/news_rg_preflight_v1.py" inspect
echo NEWS_RG_EXISTING_TELEGRAM_BOT_AND_CHANNEL_UNTOUCHED
