#!/usr/bin/env python3
"""RG News2 durable callback service; stage-only until owner evidence is verified.

Actions: install, status, disable. Install NEVER enables polling.
To enable, independently verify owner and follow a separate reviewed cutover.
"""
import datetime,json,os,pathlib,shutil,stat,subprocess,sys,tempfile
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
CRON=pathlib.Path('/etc/crontab')
SOURCE=O/'rg_news2_controlled_callback_once_v1.py'
TARGET=O/'callback_service_v1.sh'
MARK='# RG_NEWS2_CALLBACK_SERVICE_V1'
CONTENT='''#!/bin/sh
set -eu
BASE=/volume1/docker/RG_TELEGRAM_NEWS_2
test -f "$BASE/MODERATION_DELIVERY_ENABLED" || exit 0
test -f "$BASE/NAS_EXCLUSIVE_OWNER_VERIFIED" || exit 0
test ! -e "$BASE/PUBLISH_ENABLED" || exit 0
test ! -e /volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled || exit 0
test -f "$BASE/operator/rg_news2_controlled_callback_once_v1.py" || exit 0
/usr/bin/python3 "$BASE/operator/rg_news2_controlled_callback_once_v1.py" once
'''
# NOTE: existing one-shot rejects OWNER marker; until it is adapted and
# revalidated, launcher is intentionally not enabled anywhere.
def emit(**kw):print(json.dumps(kw,ensure_ascii=False,sort_keys=True))
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ('install','status','disable'):raise RuntimeError('USAGE_INSTALL_STATUS_DISABLE')
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink():raise RuntimeError('UNSAFE_OPERATOR_DIR')
 if not CRON.is_file() or CRON.is_symlink():raise RuntimeError('CRON_UNAVAILABLE')
 cron=CRON.read_text('utf-8')
 if MARK in cron:raise RuntimeError('UNEXPECTED_CALLBACK_CRON_REVIEW_REQUIRED')
 action=sys.argv[1]
 if action=='status':
  emit(status='CALLBACK_SERVICE_STAGED' if TARGET.is_file() else 'NOT_STAGED',polling_enabled=False,channel_sends=0,owner_proven=False);return
 if action=='disable':
  if TARGET.is_file():
   TARGET.rename(O/('callback_service.disabled_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
  emit(status='CALLBACK_SERVICE_DISABLED',cron_changed=False,polling_enabled=False);return
 if not SOURCE.is_file() or SOURCE.is_symlink():raise RuntimeError('TESTED_ONESHOT_MODULE_MISSING')
 text=SOURCE.read_text('utf-8')
 for token in ('updates_handoff_','process_callback','getUpdates','PUBLISH_ENABLED'):
  if token not in text:raise RuntimeError('ONESHOT_CONTRACT_MISSING')
 p=subprocess.run(['/bin/sh','-n'],input=CONTENT,universal_newlines=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if p.returncode:raise RuntimeError('INVALID_LAUNCHER')
 if TARGET.is_symlink():raise RuntimeError('TARGET_SYMLINK')
 if TARGET.is_file():
  if TARGET.read_text('utf-8')!=CONTENT:raise RuntimeError('EXISTING_DIFFERENT_LAUNCHER')
  emit(status='ALREADY_STAGED',polling_enabled=False);return
 fd,tmp=tempfile.mkstemp(dir=str(O),prefix='.callback_stage_')
 try:
  with os.fdopen(fd,'w') as f:f.write(CONTENT)
  os.chmod(tmp,0o700);os.replace(tmp,str(TARGET))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 emit(status='CALLBACK_SERVICE_STAGED_NOT_ENABLED',cron_changed=False,owner_gate_created=False,polling_enabled=False,channel_sends=0,
     next='Review polling ownership and adapt existing one-shot before any permanent schedule')
if __name__=='__main__':
 try:main()
 except Exception as e:emit(status='BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__);sys.exit(1)
