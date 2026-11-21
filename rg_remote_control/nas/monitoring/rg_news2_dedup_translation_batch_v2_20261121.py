#!/usr/bin/env python3
"""RG NEWS2 integrated remediation: actual event dedup at private-send boundary
and bounded scheduled native-video translation. Protected release, backups, fail closed.
No Telegram API calls during installation. Public publish gate remains disabled.
"""
import ast,datetime as dt,hashlib,importlib,json,os,pathlib,re,shutil,subprocess,sys,tarfile,tempfile,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
sys.path.insert(0,str(O))
PIN=O/'news_rg_guarded_release_v1.py'
MAN=O/'news_rg_stability_releases_v1/pinned_release_v1.json'
TARGET=O/'news_rg_durable_private_sender_v1.py'
CRON=pathlib.Path('/etc/crontab')
PY=O/'tools/python-3.15.2/bin/python3.15'
SCHEDULE=O/'rg_news2_translation_auto_tick_v1.py'
TRANSLATOR=O/'rg_news2_strict_native_translation_retry_v2.py'
SRC_SCHEDULE=pathlib.Path('/tmp/rg_news2_translation_auto_tick_v1.py')
SRC_TRANSLATOR=pathlib.Path('/tmp/rg_news2_strict_native_translation_retry_v2.py')
BACKUP=O/'rg_news2_dedup_translation_backups'
TAG='RG_NEWS2_TRANSLATION_RETRY_20261121'
CRONLINE=('0,15,30,45 * * * * root '+str(PY)+' '+str(SCHEDULE)
          +' >> '+str(O/'rg_news2_translation_auto_tick.log')+' 2>&1 # '+TAG+'\n')
HELPER='''
# RG_NEWS2_STRONG_CROSS_SOURCE_EVENT_DEDUP_V1
def _rg_looks_like_repeat_private_event(candidate):
    """Avoid re-sending substantially identical stories already delivered privately.
    Only PRIVATE_SENT_CONFIRMED, 12h window, exact original source or strong event overlap.
    This does not modify decisions/receipts or suppress distinct evolving reports.
    """
    import json as _j, re as _re, time as _t
    try:
        from news_rg_editorial_rank_v1 import event_duplicate as _same_event
    except (ImportError,AttributeError):
        return False
    if not isinstance(candidate,dict):return False
    current=str(candidate.get('proposed_text') or '')
    source=str(candidate.get('original_media_source') or '').strip()
    if len(current)<70:return False
    # Block only when the *other* article has already been sent privately.
    prior=set()
    for folder in (O/'news_rg_private_multipart_receipts_v1',
                   O/'news_rg_private_delivery_v2'):
        if not folder.is_dir() or folder.is_symlink():continue
        for receipt in folder.glob('*.json'):
            try:
                if receipt.is_symlink() or receipt.stat().st_size>25000:continue
                if _t.time()-receipt.stat().st_mtime>12*3600:continue
                value=_j.loads(receipt.read_text('utf8'))
                if value.get('status')!='PRIVATE_SENT_CONFIRMED':continue
                key=value.get('draft_id') or receipt.stem
                if key==candidate.get('draft_id') or key in prior:continue
                if not isinstance(key,str) or not _re.fullmatch(r'[0-9a-f]{24}',key):continue
                prior.add(key)
                staged=ST/(key+'.json')
                if staged.is_symlink() or not staged.is_file() or staged.stat().st_size>25000:continue
                earlier=_j.loads(staged.read_text('utf8'))
                if earlier.get('draft_id')!=key:continue
                previous_source=str(earlier.get('original_media_source') or '').strip()
                if source and previous_source and source==previous_source:return True
                old=str(earlier.get('proposed_text') or '')
                if len(old)<70 or not _same_event(current,old):continue
                common_words=lambda s:set(w for w in _re.findall(r'[а-яіїєґa-z0-9]{4,}',s.lower()) if w not in (
                    'цього','стало','після','раніше','пише','повідомляє','заявив','повідомили',
                    'росії','україні','російський','український','військові','відомо',
                    'новини','новина','сьогодні','даними','зокрема','також','відео'))
                a,b=common_words(current),common_words(old)
                if min(len(a),len(b))<7:continue
                if len(a&b)>=7 and len(a&b)/min(len(a),len(b))>=0.80:return True
            except (OSError,ValueError,TypeError,UnicodeError):
                continue
    return False
'''
def status(**v):print(json.dumps(v,ensure_ascii=False,indent=2),flush=True)
def ensure(x,why):
 if not x:raise RuntimeError(why)
def hashed(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(args,seconds=240):
 p=subprocess.run(args,capture_output=True,text=True,timeout=seconds)
 return p.returncode,p.stdout,p.stderr
def stage_guarded_install(current,man):
 data=TARGET.read_text('utf8')
 ensure('RG_NEWS2_STRONG_CROSS_SOURCE_EVENT_DEDUP_V1' not in data,'DEDUP_ALREADY_INSTALLED')
 ensure(data.count('def eligible():')==1,'SENDER_ELIGIBLE_FUNCTION_UNKNOWN')
 tree=ast.parse(data)
 fn=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='eligible']
 ensure(len(fn)==1,'ELIGIBLE_FUNCTION_MISSING')
 returns=[n for n in ast.walk(fn[0]) if isinstance(n,ast.Return) and isinstance(n.value,ast.Name) and n.value.id=='item']
 ensure(len(returns)==1,'ELIGIBLE_RETURN_AMBIGUOUS')
 lines=data.splitlines(keepends=True)
 idx=returns[0].lineno-1
 line=lines[idx]
 indentation=len(line)-len(line.lstrip())
 ensure(indentation>=2 and line.strip()=='return item','ELIGIBLE_RETURN_CHANGED')
 # The return must be inside a loop; otherwise "continue" would be illegal.
 ancestors=[]
 for n in ast.walk(fn[0]):
  if isinstance(n,(ast.For,ast.AsyncFor,ast.While)) and n.lineno<returns[0].lineno<=n.end_lineno:
   ancestors.append(n)
 ensure(ancestors,'ELIGIBLE_LOOP_MISSING')
 guard=' '*indentation+'if _rg_looks_like_repeat_private_event(item):continue\n'
 lines.insert(idx,guard)
 revised=''.join(lines)
 revised=revised.replace('def eligible():',HELPER+'\ndef eligible():',1)
 ast.parse(revised)
 # Test safety and actual duplicate semantics with staged fixtures before production.
 offline_test(revised)
 existing=man.get('files') or {}
 ensure(len(existing)==23 and TARGET.name in existing,'RELEASE_MANIFEST_MISMATCH')
 for name,sha in existing.items():
  p=O/name
  ensure(p.is_file() and not p.is_symlink() and hashed(p)==sha,'PIN_HASH_DRIFT_'+name)
  candidate=O/('.'+name+'.stability_candidate')
  ensure(not candidate.exists() and not candidate.is_symlink(),'FOREIGN_CANDIDATE_'+name)
 for name in existing:
  dest=O/('.'+name+'.stability_candidate')
  payload=revised.encode('utf8') if name==TARGET.name else (O/name).read_bytes()
  fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
  with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
 try:
  rc,out,err=run([str(PY),str(PIN),'install'],300)
  ensure(rc==0 and 'STABLE_RELEASE_INSTALLED' in out,
     'OFFICIAL_PIN_INSTALL_REFUSED_'+(out+' '+err)[-180:])
 finally:
  for name in existing:
   p=O/('.'+name+'.stability_candidate')
   if p.is_file() and not p.is_symlink():p.unlink()
 rc,out,err=run([str(PY),str(PIN),'status'],40)
 ensure(rc==0 and json.loads(out).get('status')=='PINNED_STABLE','RELEASE_POSTINSTALL_NOT_STABLE')
 return 'DEDUP_GUARDED_RELEASE_PASS'
def offline_test(source):
 import types
 tree=ast.parse(source)
 helper=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_rg_looks_like_repeat_private_event']
 ensure(len(helper)==1,'DEDUP_HELPER_INVALID')
 with tempfile.TemporaryDirectory(prefix='rg_dedup_offline_') as t:
  root=pathlib.Path(t);st=root/'st';st.mkdir();out=root/'news_rg_private_multipart_receipts_v1';out.mkdir()
  namespace={'O':root,'ST':st}
  exec(compile(ast.Module(body=helper,type_ignores=[]),'<rg_dedup_mock>','exec'),namespace)
  k='a'*24
  source1='У Фінській затоці російський вантажний корабель перевозив обладнання, виникла пожежа. Рятувальники повідомили про пошкодження судна та евакуацію екіпажу.'
  source2='Російський вантажний корабель перевозив обладнання у Фінській затоці, виникла пожежа. Повідомили про евакуацію екіпажу та пошкодження судна.'
  unrelated='Уряд України ухвалив програму нових грантів для підприємців і малого бізнесу. Міністерство економіки опублікувало відповідні зміни на офіційному сайті.'
  (st/(k+'.json')).write_text(json.dumps({'draft_id':k,'proposed_text':source1,'original_media_source':'https://t.me/example/123'},ensure_ascii=False),'utf8')
  (out/(k+'.json')).write_text(json.dumps({'status':'PRIVATE_SENT_CONFIRMED','draft_id':k}),'utf8')
  f=namespace['_rg_looks_like_repeat_private_event']
  ensure(f({'draft_id':'b'*24,'proposed_text':source2,'original_media_source':'https://t.me/example/123'}),'EXACT_SOURCE_DEDUP_FAIL')
  ensure(not f({'draft_id':'b'*24,'proposed_text':unrelated,'original_media_source':'https://t.me/example/124'}),'UNRELATED_NEWS_BLOCKED')
  ensure(not f({'draft_id':'b'*24,'proposed_text':unrelated,'original_media_source':'https://t.me/example/1234'}),'FALSE_DUPLICATE')
def safe_copy(src,dst):
 ensure(src.is_file() and not src.is_symlink(),'SOURCE_MISSING_'+src.name)
 data=src.read_bytes()
 ensure(len(data)<35000,'SCRIPT_TOO_LARGE')
 ast.parse(data.decode('utf8'))
 fd,tmp=tempfile.mkstemp(dir=O,prefix='.rg_stage_')
 try:
  os.fchmod(fd,0o700)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,dst)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def cron_install():
 ensure(CRON.is_file() and not CRON.is_symlink(),'CRONTAB_UNSAFE')
 current=CRON.read_text('utf8')
 if TAG in current:
  ensure(current.count(TAG)==1 and CRONLINE.strip() in current,'CRONTAB_RULE_CHANGED')
  return 'ALREADY_SCHEDULED'
 ensure('root' in current and len(current)<120000,'CRONTAB_CONTENT_UNEXPECTED')
 with open(CRON,'a',encoding='utf8') as f:
  if current and not current.endswith('\n'):f.write('\n')
  f.write(CRONLINE);f.flush();os.fsync(f.fileno())
 ensure(CRONLINE.strip() in CRON.read_text('utf8'),'CRON_VERIFY_FAILED')
 # Synology crond polls /etc/crontab. Explicit reload when supported is best-effort.
 rc,out,err=run(['/usr/syno/bin/synosystemctl','reload','crond'],15)
 return 'SCHEDULE_INSTALLED_RELOAD_OK' if rc==0 else 'SCHEDULE_INSTALLED_RELOAD_UNCONFIRMED'
def main():
 ensure(os.geteuid()==0,'SUDO_REQUIRED')
 ensure(not (B/'PUBLISH_ENABLED').exists() and not (B/'PUBLISH_ENABLED').is_symlink(),'PUBLICATION_GATE_OPEN')
 ensure(PY.is_file() and PIN.is_file() and MAN.is_file(),'RELEASE_FILES_MISSING')
 ensure(CRON.is_file() and not CRON.is_symlink(),'CRON_MISSING')
 ensure(SRC_SCHEDULE.is_file() and SRC_TRANSLATOR.is_file(),'TRANSLATION_SOURCES_MISSING')
 ensure(not SCHEDULE.is_symlink() and not TRANSLATOR.is_symlink(),'WORKER_SYMLINK')
 # All checks before attempting official pinned release.
 manifest=json.loads(MAN.read_text('utf8'))
 current=TARGET.read_text('utf8')
 ensure(current.count('def eligible():')==1,'SENDER_ELIGIBLE_UNKNOWN')
 ensure('RG_NEWS2_STRONG_CROSS_SOURCE_EVENT_DEDUP_V1' not in current,'ALREADY_PATCHED_STOP')
 for source in (SRC_SCHEDULE,SRC_TRANSLATOR):ast.parse(source.read_text('utf8'))
 ensure('RG_TRANSLATION_SKIP_PENDING_IDS' in SRC_TRANSLATOR.read_text('utf8'),'TRANSLATION_COOLDOWN_CONTRACT_MISSING')
 rc,out,err=run([str(PY),str(PIN),'status'],35)
 ensure(rc==0 and json.loads(out).get('status')=='PINNED_STABLE','PINNED_RELEASE_NOT_HEALTHY')
 BACKUP.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(BACKUP,0o700)
 stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 package=BACKUP/('before_'+stamp+'.tar.gz')
 with tarfile.open(package,'w:gz') as a:
  a.add(MAN,arcname='pinned_release_v1.json',recursive=False)
  for n in manifest['files']:a.add(O/n,arcname='modules/'+n,recursive=False)
  a.add(CRON,arcname='etc_crontab',recursive=False)
  for p in (SCHEDULE,TRANSLATOR):
   if p.exists() and p.is_file():a.add(p,arcname='existing_scripts/'+p.name,recursive=False)
 os.chmod(package,0o600)
 # Don't stage cron first: ensure release is correct before enabling automation.
 official=stage_guarded_install(current,manifest)
 safe_copy(SRC_SCHEDULE,SCHEDULE)
 safe_copy(SRC_TRANSLATOR,TRANSLATOR)
 rc,out,err=run([str(PY),str(SCHEDULE),'--selftest'],90)
 ensure(rc==0 and json.loads(out).get('status')=='TRANSLATION_SCHEDULER_SELFTEST_PASS','SCHEDULE_SMOKE_TEST_FAILED_'+(out+err)[-120:])
 scheduled=cron_install()
 status(result='NEWS2_EVENT_DEDUP_AND_TRANSLATION_SCHEDULER_INSTALLED',
  official_release=official,private_event_dedup='STRONG_SOURCE_OR_EVENT_12H',
  translation_frequency='EVERY_15_MINUTES',
  translation_backoff_hours=12,translation_worker_test=json.loads(out).get('status'),
  cron_status=scheduled,backup=str(package),original_video_file_ids_preserved=True,
  protected_modules=23,publication_gate='OFF',telegram_calls_during_install=0,
  public_posts=0,new_pollers=0)
if __name__=='__main__':
 try:main()
 except Exception as exc:
  status(result='SAFE_STOP',error_type=type(exc).__name__,reason=str(exc)[:210],
    public_posts=0,new_pollers=0)
  sys.exit(2)
