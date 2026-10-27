#!/bin/sh
# Strictly ONE optional Gemini rewrite for NEWS RG; no Telegram send or poll.
# Uses existing R7 Gemini key only if locally available, and does not change
# the active bot, scheduler, callback, current news.sqlite3 or publication gate.
set -eu
umask 077
if [ "$(id -u)" -ne 0 ]; then
  echo NEWS_RG_AI_PILOT_ROOT_REQUIRED
  exit 2
fi
DIR='/tmp/news_rg_one_news_pilot_v1'
BASE='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/ece66d8d52fb844ad5af7948e21fd26f21930840/rg_remote_control/nas/monitoring'
if [ -L "$DIR" ]; then
  echo NEWS_RG_AI_PILOT_PATH_SYMLINK_STOP
  exit 2
fi
mkdir -p "$DIR"
chmod 700 "$DIR"
for name in \
  news_rg_editorial_contract_v1.py \
  news_rg_editorial_rewrite_shadow_v1.py \
  news_rg_ai_owner_discovery_v1.py \
  news_rg_pilot_one_editorial_v1.py \
  news_rg_editorial_draft_preview_v1.py
do
  if [ -L "$DIR/$name" ]; then
    echo NEWS_RG_AI_PILOT_FILE_SYMLINK_STOP
    exit 2
  fi
  curl -fsSL --connect-timeout 10 --max-time 40 "$BASE/$name" -o "$DIR/$name"
  chmod 600 "$DIR/$name"
  /usr/bin/python3 -m py_compile "$DIR/$name"
  /usr/bin/python3 "$DIR/$name" selftest
done
echo '=== EXISTING NAS R7 CONTENT HUB PROVIDER (NO SECRET VALUES) ==='
/usr/bin/python3 "$DIR/news_rg_ai_owner_discovery_v1.py" inspect
echo '=== ONE DRAFT FROM EXISTING PROVIDER IF CREDENTIAL AVAILABLE ==='
# This one explicit run can consume AT MOST ONE Google Gemini AI request.
/usr/bin/python3 "$DIR/news_rg_pilot_one_editorial_v1.py" pilot-one
echo '=== DRAFT QUALITY (NO PUBLIC CHANNEL OR TELEGRAM SEND) ==='
/usr/bin/python3 "$DIR/news_rg_editorial_draft_preview_v1.py" inspect
echo NEWS_RG_EDITORIAL_ONE_DRAFT_PILOT_COMPLETE_NO_TELEGRAM_SEND
