#!/usr/bin/env python3
"""Install RG NEWS2 daily audit, run one controlled translation tick, assess.
No public sends, no second poller, retain prior cron and backups.
"""
import ast,datetime as dt,json,os,pathlib,subprocess,sys,tarfile,tempfile,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
PY=O/'tools/python-3.15.2/bin/python3.15'
SOURCE=pathlib.Path('/tmp/rg_news2_daily_quality_audit_v1.py')
DST=O/'rg_news2_daily_quality_audit_v1.py'
CRON=pathlib.Path('/etc/crontab')
TAG='RG_NEWS2_DAILY_QUALITY_20261121'
LINE=('10 8 * * * root '+str(PY)+' '+str(DST)+' --once >> '+
 str(O/'rg_news2_daily_quality_audit.log')+' 2>&1 # '+TAG+'\n')
BACK=O/'rg_news2_daily_quality_install_backups'
TRANSLATION=O/'rg_news2_translation_auto_tick_v1.py'
def info(**args):print(json.dumps(args,ensure_ascii=False,indent=2),flush=True)
def need(ok,why):
 if not ok:raise RuntimeError(why)
def exec_cmd(args,timeout=120):
 p=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
 return p.returncode,p.stdout,p.stderr
def atomic_copy(source,target):
 raw=source.read_bytes();ast.parse(raw.decode('utf8'))
 fd,tmp=tempfile.mkstemp(prefix='.rg_audit_',dir=target.parent)
 try:
  os.fchmod(fd,0o700)
  with os.fdopen(fd,'wb') as f:
   f.write(raw);f.flush();os.fsync(f.fileno())
  os.replace(tmp,target)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def main():
 need(os.geteuid()==0,'SUDO_REQUIRED')
 need(not (B/'PUBLISH_ENABLED').exists() and not (B/'PUBLISH_ENABLED').is_symlink(),'PUBLIC_GATE_OPEN')
 need(SOURCE.is_file() and not SOURCE.is_symlink() and SOURCE.stat().st_size<35000,'AUDIT_SOURCE_MISSING')
 need(CRON.is_file() and not CRON.is_symlink(),'CRON_UNSAFE')
 need(PY.is_file() and TRANSLATION.is_file(),'RUNTIME_MISSING')
 pin=O/'news_rg_guarded_release_v1.py'
 rc,out,err=exec_cmd([str(PY),str(pin),'status'],45)
 need(rc==0 and json.loads(out).get('status')=='PINNED_STABLE','GUARDED_RELEASE_DRIFT')
 rc,out,err=exec_cmd([str(PY),str(SOURCE),'--selftest'],20)
 need(rc==0 and json.loads(out).get('status')=='DAILY_AUDIT_SELFTEST_PASS','AUDIT_SELFTEST_FAIL')
 cron=CRON.read_text('utf8')
 if TAG in cron:need(cron.count(TAG)==1 and LINE.strip() in cron,'EXISTING_AUDIT_CRON_DRIFT')
 BACK.mkdir(mode=0o700,exist_ok=True);os.chmod(BACK,0o700)
 stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 package=BACK/('before_'+stamp+'.tar.gz')
 with tarfile.open(package,'w:gz') as ar:
  ar.add(CRON,arcname='etc_crontab',recursive=False)
  if DST.exists():
   need(not DST.is_symlink() and DST.is_file(),'EXISTING_AUDIT_UNSAFE')
   ar.add(DST,arcname='existing_audit.py',recursive=False)
 os.chmod(package,0o600)
 old= DST.read_bytes() if DST.exists() else None
 appended=False
 try:
  atomic_copy(SOURCE,DST)
  rc,out,err=exec_cmd([str(PY),str(DST),'--once'],100)
  need(rc==0,'FIRST_AUDIT_FAILED_'+(out+err)[-140:])
  first=json.loads(out)
  if TAG not in cron:
   with CRON.open('a',encoding='utf8') as f:
    if cron and not cron.endswith('\n'):f.write('\n')
    f.write(LINE);f.flush();os.fsync(f.fileno())
   appended=True
  need(LINE.strip() in CRON.read_text('utf8'),'DAILY_CRON_VERIFY_FAILED')
  reload_rc,reload_out,reload_err=exec_cmd(['/usr/syno/bin/synosystemctl','reload','crond'],20)
 except Exception:
  if appended:CRON.write_text(cron,'utf8')
  if old is None and DST.exists():DST.unlink()
  elif old is not None:
   fd,tmp=tempfile.mkstemp(dir=O,prefix='.rg_audit_restore_')
   with os.fdopen(fd,'wb') as f:f.write(old);f.flush();os.fsync(f.fileno())
   os.chmod(tmp,0o700);os.replace(tmp,DST)
  raise
 # One controlled run. This may send ONE NEW private moderation card;
 # no public send, no new poller. All at-most-once receipts enforced by pinned sender.
 translation={'status':'NOT_RUN'}
 try:
  r,t,e=exec_cmd([str(PY),str(TRANSLATION)],280)
  try:translation=json.loads(t)
  except Exception:translation={'status':'UNKNOWN','returncode':r}
 except Exception as ex:translation={'status':'SAFE_STOP','error_type':type(ex).__name__}
 # Re-audit immediately to capture attempt and any new private staging.
 rc,out,err=exec_cmd([str(PY),str(DST),'--once'],100)
 need(rc==0,'POST_TRANSLATION_AUDIT_FAILED')
 second=json.loads(out)
 info(status='RG_NEWS2_BATCH_AUDIT_AND_SCHEDULE_INSTALLED',
  release='PINNED_STABLE',daily_report_time='08:10 NAS local time',
  daily_schedule='INSTALLED',cron_reload='PASS' if reload_rc==0 else 'UNCONFIRMED',
  backup=str(package),
  translation_tick=translation,
  audit_status=second.get('status'),
  audit_alerts=second.get('alerts',[]),
  daily_report_path=str(O/'rg_news2_daily_quality_report_v1.json'),
  translation_pending=second['translation'].get('pending_count'),
  private_delivery_unresolved=second['delivery'].get('unresolved_count'),
  recent_exact_repeat_pairs=second['delivery'].get('confirmed_recent_exact_repeat_pairs'),
  canonical_footer_ok=second['content'].get('footer_link_pass'),
  obsolete_questions_removed=second['content'].get('footer_cleaning_pass'),
  public_auto_gate='OFF',new_pollers=0,publications_triggered_by_install=0)
if __name__=='__main__':
 try:main()
 except Exception as ex:
  info(status='SAFE_STOP',reason=str(ex)[:180],new_pollers=0)
  sys.exit(2)
