#!/usr/bin/env python3
"""Activate the staged News2 outbound-only queue every five minutes.
Idempotent root crontab change with backup and rollback on verification failure.
Never polls getUpdates, opens gates, or publishes to the channel.
"""
import datetime,json,os,pathlib,subprocess,sys,tempfile
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
RUN=BASE/'operator/outbound_tick.sh'
BACK=BASE/'operator'
MARK='# RG_NEWS2_OUTBOUND_QUEUE_V1'
LINE='*/5 * * * * /bin/sh /volume1/docker/RG_TELEGRAM_NEWS_2/operator/outbound_tick.sh >> /volume1/docker/RG_TELEGRAM_NEWS_2/operator/outbound_tick.log 2>&1 '+MARK
def emit(**kw):print(json.dumps(kw,ensure_ascii=False,sort_keys=True))
def cmd(a,input=None):
 p=subprocess.run(a,input=input,universal_newlines=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 return p
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ('enable','status','disable'):raise RuntimeError('USAGE_ENABLE_STATUS_DISABLE')
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not RUN.is_file() or RUN.is_symlink():raise RuntimeError('STAGED_RUNNER_MISSING')
 content=RUN.read_text('utf-8')
 if 'rg_news2_outbound_queue_v2.py tick' not in content or 'getUpdates' in content or 'poll-once' in content:raise RuntimeError('RUNNER_UNRECOGNIZED')
 if (BASE/'PUBLISH_ENABLED').exists() or pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled').exists():raise RuntimeError('UNSAFE_EXISTING_GATE')
 if not (BASE/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('DELIVERY_NOT_ENABLED')
 if BACK.is_symlink() or not BACK.is_dir():raise RuntimeError('BACKUP_DIR_UNSAFE')
 q=cmd(['crontab','-l'])
 if q.returncode!=0 and q.stdout.strip():raise RuntimeError('CRONTAB_LIST_ERROR')
 if q.returncode!=0 and not any(x in q.stderr.lower() for x in ('no crontab','no crontab for')):raise RuntimeError('CRONTAB_READ_FAILED')
 original=q.stdout if q.returncode==0 else ''
 lines=original.splitlines()
 matching=[x for x in lines if MARK in x]
 if any(x!=LINE for x in matching):raise RuntimeError('EXISTING_MARKER_DRIFT')
 if sys.argv[1]=='status':
  emit(status='ENABLED' if LINE in lines else 'DISABLED',cron_5min=LINE in lines,channel_publish_enabled=False,telegram_poll_enabled=False)
  return
 filtered=[x for x in lines if MARK not in x]
 if sys.argv[1]=='enable':filtered.append(LINE)
 new='\n'.join(filtered).rstrip()+'\n'
 if new==original:
  emit(status='ALREADY_'+('ENABLED' if sys.argv[1]=='enable' else 'DISABLED'),schedule_changed=False);return
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 dest=BACK/('root_crontab_before_news2_'+stamp+'.txt')
 if dest.exists() or dest.is_symlink():raise RuntimeError('BACKUP_NAME_COLLISION')
 dest.write_text(original,encoding='utf-8');os.chmod(str(dest),0o600)
 result=cmd(['crontab','-'],new)
 if result.returncode:raise RuntimeError('CRONTAB_INSTALL_FAILED')
 check=cmd(['crontab','-l'])
 if check.returncode or check.stdout!=new:
  cmd(['crontab','-'],original)
  raise RuntimeError('CRONTAB_VERIFY_FAILED_ROLLBACK_ATTEMPTED')
 emit(status='SCHEDULE_ENABLED' if sys.argv[1]=='enable' else 'SCHEDULE_DISABLED',every_minutes=5,backup=str(dest),channel_sends=0,telegram_polls=0,publish_gate_unchanged=True)
if __name__=='__main__':
 try:main()
 except Exception as ex:
  emit(status='BLOCKED',reason=str(ex) if isinstance(ex,RuntimeError) else type(ex).__name__)
  sys.exit(1)
