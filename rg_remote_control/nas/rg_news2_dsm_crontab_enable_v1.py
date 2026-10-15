#!/usr/bin/env python3
"""DSM /etc/crontab News2 outbound-only every-five-minute schedule.
Atomic file edit, backup, idempotent. No getUpdates, no publishing.
"""
import datetime,json,os,pathlib,stat,subprocess,sys,tempfile
CRON=pathlib.Path('/etc/crontab')
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
RUN=OP/'outbound_tick.sh'
MARK='# RG_NEWS2_OUTBOUND_QUEUE_V1'
ENTRY='*/5\t*\t*\t*\t*\troot\t/bin/sh /volume1/docker/RG_TELEGRAM_NEWS_2/operator/outbound_tick.sh >> /volume1/docker/RG_TELEGRAM_NEWS_2/operator/outbound_tick.log 2>&1 '+MARK
def emit(**x):print(json.dumps(x,ensure_ascii=False,sort_keys=True))
def main():
 mode=sys.argv[1] if len(sys.argv)==2 else ''
 if mode not in ('enable','status','disable'):raise RuntimeError('USAGE_ENABLE_STATUS_DISABLE')
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not CRON.is_file() or CRON.is_symlink():raise RuntimeError('DSM_CRONTAB_MISSING_OR_SYMLINK')
 if not RUN.is_file() or RUN.is_symlink():raise RuntimeError('STAGED_RUNNER_MISSING')
 if OP.is_symlink():raise RuntimeError('UNSAFE_OPERATOR_DIR')
 runner=RUN.read_text('utf-8')
 if 'rg_news2_outbound_queue_v2.py tick' not in runner or 'getUpdates' in runner or 'poll-once' in runner:raise RuntimeError('UNRECOGNIZED_RUNNER')
 if (BASE/'PUBLISH_ENABLED').exists():raise RuntimeError('PUBLISH_GATE_OPEN')
 if pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled').exists():raise RuntimeError('LEGACY_GATE_OPEN')
 original=CRON.read_text('utf-8')
 if not original.endswith('\n'):raise RuntimeError('UNEXPECTED_CRONTAB_NO_FINAL_NEWLINE')
 lines=original.splitlines()
 if not any(len(x.split())>=7 and x.split()[5]=='root' for x in lines if x.strip() and not x.lstrip().startswith('#')):
  raise RuntimeError('DSM_CRONTAB_FORMAT_UNVERIFIED')
 present=[x for x in lines if MARK in x]
 if any(x!=ENTRY for x in present):raise RuntimeError('EXISTING_MARKER_DIFFERENT')
 if mode=='status':
  emit(status='ENABLED' if ENTRY in present else 'DISABLED',schedule_every_5min=ENTRY in present,cron_file=str(CRON),cron_daemon_reload_verified=False);return
 if mode=='enable':
  if not (BASE/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('DELIVERY_GATE_CLOSED')
  newlines=[x for x in lines if MARK not in x]+[ENTRY]
 else:newlines=[x for x in lines if MARK not in x]
 result='\n'.join(newlines)+'\n'
 if result==original:
  emit(status='ALREADY_ENABLED' if mode=='enable' else 'ALREADY_DISABLED',cron_daemon_reload_verified=False);return
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=OP/('etc_crontab_backup_'+stamp)
 if backup.exists() or backup.is_symlink():raise RuntimeError('BACKUP_COLLISION')
 fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:f.write(original);f.flush();os.fsync(f.fileno())
 s=CRON.stat()
 fd,tmp=tempfile.mkstemp(prefix='.rg_news2_crontab_',dir=str(CRON.parent))
 try:
  with os.fdopen(fd,'w') as f:f.write(result);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,stat.S_IMODE(s.st_mode))
  os.chown(tmp,s.st_uid,s.st_gid)
  os.replace(tmp,str(CRON))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 if CRON.read_text('utf-8')!=result:raise RuntimeError('CRONTAB_READBACK_FAILED')
 emit(status='DSM_CRONTAB_'+('ENABLED' if mode=='enable' else 'DISABLED'),
      schedule_every_5min=mode=='enable',backup=str(backup),
      cron_daemon_reload_verified=False,
      next='Verify cron daemon discovers edited /etc/crontab and tick log',
      telegram_polls=0,channel_sends=0)
if __name__=='__main__':
 try:main()
 except Exception as ex:
  emit(status='BLOCKED',reason=str(ex) if isinstance(ex,RuntimeError) else type(ex).__name__)
  sys.exit(1)
