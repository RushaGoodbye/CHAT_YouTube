#!/usr/bin/env python3
"""Safe NEWS RG stability -> EXISTING Gatus/DSM integration with full rollback.

Adds one Gatus external endpoint and one hook into existing DSM task #4 script.
Only Gatus container is restarted (once) to apply config; Observer, Telegram
callback owner, publication, AI, and all task registrations remain unchanged.
Requires one root-run opt-in 'install'. No Gatus alert provider is enabled.
"""
import os,sys,json,re,subprocess,hashlib,stat,shutil,pathlib,tempfile,time,urllib.request,secrets,fcntl
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
TICK=BASE/'rg_news_dsm_tick.sh'
INSTALLER_MARK='# NEWS_RG_GATUS_STABILITY_MONITOR_V1'
ACT=OP/'news_rg_gatus_monitor_activation_v1.json'
HEALTH=OP/'news_rg_stability_healthcheck_v1.py'
PUSH=OP/'news_rg_gatus_health_push_v1.py'
TOKEN=OP/'news_rg_gatus_stability_token_v1'
HEALTH_SOURCE=pathlib.Path('/tmp/news_rg_health.py')
PUSH_SOURCE=pathlib.Path('/tmp/news_rg_gatus_health_push_v1.py')
BACKUP_CONFIG=OP/'news_rg_gatus_config_pre_stability_v1.backup'
BACKUP_TICK=OP/'rg_news_dsm_tick_pre_gatus_v1.backup'
KEY='rg-nas_news-rg-stability'
NAME='news-rg-stability'
GROUP='rg-nas'
DOCKER='rg-nas-gatus'
LOCAL='http://127.0.0.1:18080/'
def fail(s):raise RuntimeError(s)
def emit(**x):print(json.dumps(x,ensure_ascii=False,sort_keys=True))
def command(args,timeout=15,check=True):
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=timeout)
 if check and p.returncode:fail('COMMAND_FAILED_'+str(args[0]).rsplit('/',1)[-1])
 return p.returncode,p.stdout.decode('utf8','replace')
def docker():
 p=shutil.which('docker') or ('/usr/local/bin/docker' if pathlib.Path('/usr/local/bin/docker').is_file() else None)
 if not p:fail('DOCKER_NOT_AVAILABLE')
 return p
def get_cont(exe):
 _,raw=command([exe,'inspect',DOCKER])
 obj=json.loads(raw)[0]
 if obj.get('State',{}).get('Running') is not True:fail('GATUS_NOT_RUNNING')
 if str(obj.get('Config',{}).get('Image',''))!='ghcr.io/twin/gatus:v5.37.0':
  fail('GATUS_IMAGE_CHANGED')
 return obj
def gatus_config(cont):
 options=[]
 for m in cont.get('Mounts') or []:
  if m.get('Type')!='bind' or '/config' not in str(m.get('Destination','')).lower():continue
  src=pathlib.Path(str(m.get('Source','')))
  if src.is_symlink():fail('GATUS_MOUNT_SYMLINK')
  if src.is_file() and src.suffix.lower() in ('.yml','.yaml'):
   options.append((src,True))
  elif src.is_dir():
   for q in (src/'config.yaml',src/'config.yml',src/'gatus'/'config.yaml',src/'gatus'/'config.yml'):
    if q.is_file() and not q.is_symlink():options.append((q,False))
 # Exactly one file from the existing Gatus container, never guess one.
 options=list({str(p):(p,b) for p,b in options}.values())
 if len(options)!=1:fail('GATUS_CONFIG_NOT_UNAMBIGUOUS')
 path,file_bind=options[0]
 if path.stat().st_size>500000:fail('GATUS_CONFIG_OVERSIZE')
 return path,file_bind
def health_http():
 try:
  with urllib.request.urlopen(LOCAL,timeout=5) as res:return res.status==200
 except Exception:return False
def yaml_patch(original,token):
 if not original.endswith('\n'):fail('GATUS_CONFIG_NO_FINAL_NEWLINE')
 if original.count('\nexternal-endpoints:')+int(original.startswith('external-endpoints:'))!=1:
  fail('GATUS_EXTERNAL_SECTION_NOT_UNIQUE')
 if re.search(r'(?m)^\s*name:\s*["\']?'+re.escape(NAME)+r'["\']?\s*$',original):
  fail('GATUS_STABILITY_ALREADY_DEFINED')
 for expected in ('news2-callback-state','news2-callback-log'):
  if len(re.findall(r'(?m)^\s*-\s*name:\s*["\']?'+re.escape(expected)+r'["\']?\s*$',original))!=1:
   fail('EXISTING_ENDPOINTS_NOT_VERIFIED_'+expected)
 lines=original.splitlines(keepends=True)
 index=next(i for i,line in enumerate(lines) if line.strip()=='external-endpoints:' and line[0]=='e')
 end=len(lines)
 for i in range(index+1,len(lines)):
  if re.match(r'^[A-Za-z0-9_-][A-Za-z0-9_-]*\s*:',lines[i]):
   end=i;break
 # Append within external-endpoints section, without altering existing entries.
 block=(
  '  - name: '+NAME+'\n'
  '    group: '+GROUP+'\n'
  '    token: "'+token+'"\n'
  '    heartbeat:\n'
  '      interval: 2h\n')
 out=''.join(lines[:end])+block+''.join(lines[end:])
 if out.count('    token: "'+token+'"')!=1 or out.count('name: '+NAME)!=1:
  fail('PATCH_CONTRACT_UNEXPECTED')
 if '    token: "'+token+'"' in original:fail('TOKEN_ALREADY_IN_CONFIG')
 return out
def tick_patch(text):
 if INSTALLER_MARK in text:fail('DSM_MONITOR_HOOK_ALREADY_PRESENT')
 for key in ('news_rg_safe_schedule_v2.py','news_rg_private_dispatch_schedule_v1.py',
             'news_rg_publication_schedule_v1.py'):
  if text.count(key)!=1:fail('DSM_NEWS_HOOK_MISSING_'+key)
 if not text.rstrip().endswith('exit 0'):fail('DSM_TICK_LAYOUT_CHANGED')
 where=text.rfind('exit 0')
 patched=text[:where]+INSTALLER_MARK+'''
# Reuse DSM task #4; Gatus-only health push, never Telegram or AI.
/usr/bin/python3 '/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_gatus_health_push_v1.py' tick >/dev/null 2>&1 || :
'''+text[where:]
 p=subprocess.run(['sh','-n'],input=patched.encode(),capture_output=True,timeout=5)
 if p.returncode:fail('DSM_SHELL_SYNTAX_INVALID')
 return patched
def preflight():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 for p in (BASE,OP):
  if p.is_symlink() or not p.is_dir():fail('BASE_UNSAFE')
 if ACT.exists():
  a=json.loads(ACT.read_text('utf8'))
  if a.get('schema')=='NEWS_RG_GATUS_MONITOR_ACTIVATION_V1' and a.get('status')=='ACTIVE':
   return {'status':'ALREADY_ACTIVE','gatus_restart_needed':False},None
  fail('EXISTING_ACTIVATION_UNEXPECTED')
 for p in (BACKUP_CONFIG,BACKUP_TICK,HEALTH,PUSH,TOKEN):
  if p.exists() or p.is_symlink():fail('INSTALL_TARGET_EXISTS_'+p.name)
 for src,mark in ((HEALTH_SOURCE,'NEWS_RG_STABILITY_V1'),(PUSH_SOURCE,'NEWS_RG_GATUS_STABILITY_PUSH_V1')):
  if src.is_symlink() or not src.is_file() or src.stat().st_size>80000:fail('STAGED_SOURCE_MISSING')
  if mark not in src.read_text('utf8'):fail('STAGED_SOURCE_UNEXPECTED')
  command(['/usr/bin/python3','-m','py_compile',str(src)])
  code,txt=command(['/usr/bin/python3',str(src),'selftest'],timeout=10)
  if 'SELFTEST_PASS' not in txt:fail('STAGED_SOURCE_SELFTEST_FAIL')
 exe=docker()
 cont=get_cont(exe)
 path,file_bind=gatus_config(cont)
 if not health_http():fail('GATUS_HTTP_NOT_HEALTHY_BEFORE_CHANGE')
 raw=path.read_bytes()
 cfg=raw.decode('utf8')
 tick=TICK.read_text('utf8')
 if TICK.is_symlink() or not TICK.is_file() or TICK.stat().st_size>50000:fail('DSM_TICK_UNSAFE')
 # Check task #4 without changing any task.
 task=next((p for p in ('/usr/syno/bin/synoschedtask','/usr/syno/sbin/synoschedtask')
            if pathlib.Path(p).is_file()),None)
 if not task:fail('DSM_TASK_CLI_MISSING')
 _,tasktext=command([task,'--get','id=4'])
 if 'rg_news_dsm_tick' not in tasktext:fail('DSM_TASK_4_MISMATCH')
 if not re.search(r'(?im)^\s*State\s*:\s*\[\s*enabled\s*\]',tasktext):
  fail('DSM_TASK_4_NOT_PROVEN_ENABLED')
 # Generate preview with a fake token; real token is minted only during install.
 yaml_patch(cfg,'a'*48)
 tick_patch(tick)
 return {'status':'PRECHECK_PASS','existing_gatus_endpoints_preserved':2,
    'existing_dsm_task':4,'new_dsm_tasks':0,'new_pollers':0,
    'gatus_only_restart_required':True,
    'gatus_config_bind_file':file_bind,
    'alert_delivery_included':False,'no_ai_calls':True,'no_telegram_calls':True,
    'changes':0},(exe,path,file_bind,raw,tick)
def write_file(path,data,mode=0o600,exclusive=True):
 if exclusive:
  fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 else:
  fd,name=tempfile.mkstemp(prefix='.newsrg_monitor_',dir=str(path.parent))
  try:
   with os.fdopen(fd,'wb') as f:
    os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
   os.replace(name,path)
  finally:
   if os.path.exists(name):os.unlink(name)
def set_config(path,content,mode,file_bind):
 # Bind-mounted single FILE must retain inode; directory bind can use atomic replace.
 if file_bind:
  with path.open('r+b') as f:
   f.truncate();f.write(content);f.flush();os.fsync(f.fileno())
 else:write_file(path,content,mode,exclusive=False)
def restart_gatus(exe):
 command([exe,'restart','-t','10',DOCKER],timeout=40)
 for _ in range(14):
  if health_http():return True
  time.sleep(2)
 return False
def install():
 preview,plan=preflight()
 if plan is None:return {'status':'ALREADY_ACTIVE','changes':0}
 exe,cfg,file_bind,original,tick=plan
 tmode=stat.S_IMODE(TICK.stat().st_mode)
 cmode=stat.S_IMODE(cfg.stat().st_mode)
 key=secrets.token_hex(24)
 rewritten=yaml_patch(original.decode('utf8'),key).encode('utf8')
 patched=tick_patch(tick).encode('utf8')
 oldhash=hashlib.sha256(original).hexdigest()
 written=[];config_changed=False;tick_changed=False
 # Lock prevents concurrent installer. State and file checks prevent reruns.
 lock=OP/'news_rg_gatus_monitor_install.lock'
 fd=os.open(str(lock),os.O_CREAT|os.O_RDWR,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX)
  if ACT.exists():fail('CONCURRENT_ACTIVATION')
  if hashlib.sha256(cfg.read_bytes()).hexdigest()!=oldhash or TICK.read_text('utf8')!=tick:
   fail('CONCURRENT_CONFIG_CHANGE')
  try:
   write_file(BACKUP_CONFIG,original);written.append(BACKUP_CONFIG)
   write_file(BACKUP_TICK,tick.encode('utf8'));written.append(BACKUP_TICK)
   write_file(HEALTH,HEALTH_SOURCE.read_bytes());written.append(HEALTH)
   write_file(PUSH,PUSH_SOURCE.read_bytes());written.append(PUSH)
   write_file(TOKEN,(key+'\n').encode('ascii'));written.append(TOKEN)
   # Validate staged copies before touching live configuration.
   for path in (HEALTH,PUSH):
    _,check=command(['/usr/bin/python3',str(path),'selftest'],timeout=10)
    if 'SELFTEST_PASS' not in check:fail('COPIED_MODULE_SELFTEST_FAILED')
   set_config(cfg,rewritten,cmode,file_bind);config_changed=True
   # Apply via single Gatus-only restart. No Telegram, Observer, NAS reboot.
   if not restart_gatus(exe):fail('GATUS_RESTART_OR_HTTP_FAILED')
   # New endpoint receives a signed heartbeat. This verifies token and routing.
   rc,out=command(['/usr/bin/python3',str(PUSH),'tick'],timeout=50,check=False)
   if rc or 'GATUS_PUSH_CONFIRMED' not in out:fail('GATUS_EXTERNAL_PUSH_NOT_CONFIRMED')
   # Only after Gatus verified do we arm an existing DSM task hook.
   write_file(TICK,patched,tmode,exclusive=False);tick_changed=True
   if TICK.read_bytes()!=patched:fail('DSM_HOOK_WRITE_MISMATCH')
   active={'schema':'NEWS_RG_GATUS_MONITOR_ACTIVATION_V1','status':'ACTIVE',
      'activated_at':int(time.time()),'channel_publications':0,'new_tasks':0,
      'gatus_external_key':KEY,'config_sha_before':oldhash,
      'config_sha_after':hashlib.sha256(rewritten).hexdigest(),
      'backup_config':str(BACKUP_CONFIG),'backup_tick':str(BACKUP_TICK)}
   write_file(ACT,json.dumps(active,sort_keys=True).encode());written.append(ACT)
   return {'status':'NEWS_RG_GATUS_MONITOR_ACTIVE','endpoint_key':KEY,
     'gatus_http_200':health_http(),'initial_push_confirmed':True,
     'previous_gatus_endpoints_preserved':2,'existing_task_4_reused':True,
     'new_dsm_tasks':0,'new_pollers':0,'telegram_calls':0,'ai_calls':0,
     'telegram_publications':0,'gatus_alerts_configured':False}
  except Exception:
   # Restore ORIGINAL config and tick and return Gatus to its previous state.
   if tick_changed:write_file(TICK,tick.encode('utf8'),tmode,exclusive=False)
   if config_changed:
    set_config(cfg,original,cmode,file_bind)
    try:restart_gatus(exe)
    except Exception:pass
   for p in reversed(written):
    try:
     if p.is_file() and not p.is_symlink():p.unlink()
    except OSError:pass
   raise
 finally:os.close(fd)
def selftest():
 sample=('web:\n  port: 8080\nexternal-endpoints:\n'
         '  - name: news2-callback-state\n    group: rg-nas\n    token: "A"\n'
         '  - name: news2-callback-log\n    group: rg-nas\n    token: "B"\n'
         'debug: false\n')
 patch=yaml_patch(sample,'f'*48)
 assert patch.count('  - name: ')==3
 assert patch.index('  - name: news-rg-stability')<patch.index('debug: false')
 assert patch.replace('  - name: news-rg-stability\n    group: rg-nas\n'
   '    token: "'+'f'*48+'"\n    heartbeat:\n      interval: 2h\n','')==sample
 shell='#!/bin/sh\nnews_rg_safe_schedule_v2.py\nnews_rg_private_dispatch_schedule_v1.py\nnews_rg_publication_schedule_v1.py\nexit 0\n'
 update=tick_patch(shell)
 assert update.count('news_rg_gatus_health_push_v1.py')==1
 assert update.rstrip().endswith('exit 0')
 print('NEWS_RG_GATUS_CUTOVER_INSTALLER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['preflight']:
   data,_=preflight();emit(**data)
  elif sys.argv[1:]==['install']:emit(**install())
  else:fail('EXPECTED_SELFTEST_PREFLIGHT_OR_INSTALL')
 except Exception as e:
  # Secrets, paths and raw container output never exposed.
  emit(status='SAFE_STOP',reason=str(e)[:100] if isinstance(e,RuntimeError) else type(e).__name__,
       telegram_calls=0,publications=0)
  sys.exit(2)
