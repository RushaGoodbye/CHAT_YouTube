#!/bin/sh
# NEWS RG nonpublishing source/editorial stage on an existing Synology NAS.
# No second poller, no Telegram Bot API, no public messages or changes to DSM.
set -eu
if [ "$(id -u)" != "0" ]; then
  echo 'NEWS_RG_SHADOW_STAGE_ROOT_REQUIRED'
  exit 2
fi
ROOT='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/82ce62cc24910c8dddb7f3e4bf9e93f95777dabe/rg_remote_control/nas/monitoring'
DEST='/tmp/news_rg_shadow_stage_v1'
mkdir -p "$DEST"
chmod 700 "$DEST"
for f in \
  news_rg_editorial_contract_v1.py \
  news_rg_source_shadow_ingest_v1.py \
  news_rg_editorial_rewrite_shadow_v1.py \
  news_rg_source_pipeline_probe_v1.py
do
  curl -fsSL --connect-timeout 10 --max-time 35 "$ROOT/$f" -o "$DEST/$f"
  chmod 600 "$DEST/$f"
  /usr/bin/python3 -m py_compile "$DEST/$f"
  /usr/bin/python3 "$DEST/$f" selftest
done
echo 'NEWS_RG_SHADOW_MODULES_VERIFIED'
echo '=== INSTALLED NEWS RG BOT / EDITORIAL COMPONENTS (READ ONLY) ==='
/usr/bin/python3 "$DEST/news_rg_source_pipeline_probe_v1.py" inspect-local
echo '=== 19 APPROVED TELEGRAM SOURCES INTO ISOLATED SHADOW QUEUE ==='
/usr/bin/python3 "$DEST/news_rg_source_shadow_ingest_v1.py" scan
echo 'NEWS_RG_SHADOW_STAGE_COMPLETE_NO_TELEGRAM_SEND_NO_PUBLICATION_NO_SECOND_POLLER'
