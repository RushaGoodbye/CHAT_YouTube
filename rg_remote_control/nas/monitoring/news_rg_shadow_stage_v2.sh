#!/bin/sh
# One-time NEWS RG fresh Telegram news staging and callback interface audit.
# Does NOT use Telegram Bot API, trigger moderator sends or start a poller.
# Existing DSM cron, public channel and production SQLite remain untouched.
set -eu
if [ "$(id -u)" != "0" ]; then
  printf '%s\n' NEWS_RG_SHADOW_V2_ROOT_REQUIRED
  exit 2
fi
BASE='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/56004bae64f7f519eba16657b70ec3c897737b88/rg_remote_control/nas/monitoring'
STAGE='/tmp/news_rg_shadow_stage_v2'
mkdir -p "$STAGE"
chmod 700 "$STAGE"
for f in \
    news_rg_editorial_contract_v1.py \
    news_rg_source_shadow_ingest_v1.py \
    news_rg_source_pipeline_probe_v1.py \
    news_rg_editorial_rewrite_shadow_v1.py \
    news_rg_moderator_route_probe_v1.py
do
  curl -fsSL --connect-timeout 10 --max-time 45 "$BASE/$f" -o "$STAGE/$f"
  chmod 600 "$STAGE/$f"
  /usr/bin/python3 -m py_compile "$STAGE/$f"
  /usr/bin/python3 "$STAGE/$f" selftest
done
echo '=== LIVE NEWS RG SINGLE-OWNER ROUTE INSPECTION (NO BOT CALLS) ==='
/usr/bin/python3 "$STAGE/news_rg_moderator_route_probe_v1.py" inspect
echo '=== RECENT 4-HOUR TELEGRAM MATERIALS: AT MOST 24 SHADOW DRAFT SOURCES ==='
/usr/bin/python3 "$STAGE/news_rg_source_shadow_ingest_v1.py" bootstrap-fresh
echo '=== EDITORIAL PROVIDER PREFLIGHT: AI USE EXPLICITLY DISABLED ==='
NEWS_RG_AI_ALLOWED=0 GEMINI_API_KEY= /usr/bin/python3 \
  "$STAGE/news_rg_editorial_rewrite_shadow_v1.py" rewrite
echo NEWS_RG_RECENT_SOURCE_STAGE_COMPLETE_NO_BOT_SEND_NO_PUBLICATION
