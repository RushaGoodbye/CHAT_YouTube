#!/usr/bin/env python3
"""P21 targeted child-process reaping for rg-public-monitor.
Verify exact running container, add Compose init:true to public-monitor ONLY,
validate normalized Compose before/after, then recreate ONLY that service.
No other compose services are touched; no bot settings or channels changed.
"""
import copy,datetime,json,os,pathlib,re,shutil,stat,subprocess,sys,tempfile,time
ROOT=pathlib.Path('/volume1/docker/RG_MONITOR')
COMPOSE=ROOT/'compose.yaml'
DOCKER='/usr/local/bin/docker'
SERVICE='public-monitor'
CONTAINER='rg-public-monitor'
IMAGE='rg_monitor-public-monitor'
KNOWN_PREFIX='070a14c49034'
def emit(**kw):print(json.dumps(kw,ensure_ascii=False,indent=2),flush=True)
def invoke(args,timeout=60):
 try:
  p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 except subprocess.TimeoutExpired:raise RuntimeError('COMMAND_TIMEOUT_'+args[1])
 except OSError:raise RuntimeError('COMMAND_UNAVAILABLE_'+args[0])
 if p.returncode:
  raise RuntimeError('COMMAND_FAILED_'+args[1]+'_'+str(p.returncode))
 return p.stdout.decode('utf-8','replace').strip()
def inspect():
 a=json.loads(invoke([DOCKER,'inspect',CONTAINER]))[0]
 l=a.get('Config',{}).get('Labels') or {}
 result={'id':a['Id'],'name':a.get('Name'),
 'image':a.get('Config',{}).get('Image'),
 'project':l.get('com.docker.compose.project'),
 'service':l.get('com.docker.compose.service'),
 'working_dir':l.get('com.docker.compose.project.working_dir'),
 'config_files':l.get('com.docker.compose.project.config_files'),
 'init':a.get('HostConfig',{}).get('Init'),
 'pid':a.get('State',{}).get('Pid'),
 'running':a.get('State',{}).get('Running')}
 if not (result['id'].startswith(KNOWN_PREFIX) and result['name']=='/'+CONTAINER
   and result['image']==IMAGE and result['service']==SERVICE
   and result['working_dir']==str(ROOT) and result['project']
   and result['running'] is True):
  raise RuntimeError('RUNNING_CONTAINER_IDENTITY_CHANGED_ABORT')
 # Do not silently overwrite a stack whose service comes from multiple Compose files.
 cfgs=[p.strip() for p in (result['config_files'] or '').split(',') if p.strip()]
 if cfgs!=[str(COMPOSE)]:
  raise RuntimeError('MULTI_COMPOSE_CONFIG_OR_PATH_MISMATCH_ABORT')
 return result
def patch_yaml(original):
 lines=original.splitlines(True)
 # Deliberately support only standard unambiguous Compose layout.
 roots=[i for i,s in enumerate(lines) if re.fullmatch(r'services:\\s*(?:#.*)?\\n?',s)]
 if len(roots)!=1:raise RuntimeError('NONSTANDARD_SERVICES_LAYOUT_ABORT')
 first=roots[0]
 candidates=[]
 for i in range(first+1,len(lines)):
  s=lines[i]
  if s.strip() and not s.startswith((' ','#')):break
  if re.match(r'^  public-monitor:\\s*(?:#.*)?$',s.rstrip('\\r\\n')):
   candidates.append(i)
 if len(candidates)!=1:raise RuntimeError('PUBLIC_MONITOR_SERVICE_LAYOUT_AMBIGUOUS_ABORT')
 ix=candidates[0];end=len(lines)
 for i in range(ix+1,len(lines)):
  s=lines[i]
  if not s.strip() or s.lstrip().startswith('#'):continue
  indent=len(s)-len(s.lstrip(' '))
  if indent<=2:end=i;break
 field=[]
 for i in range(ix+1,end):
  if re.match(r'^    init:\\s*',lines[i]):field.append(i)
 if len(field)>1:raise RuntimeError('DUPLICATE_INIT_FIELD_ABORT')
 if field:
  i=field[0]
  if re.fullmatch(r'    init:\\s*true\\s*(?:#.*)?\\n?',lines[i]):
   return original,False
  if not re.fullmatch(r'    init:\\s*false\\s*(?:#.*)?\\n?',lines[i]):
   raise RuntimeError('EXISTING_INIT_UNEXPECTED_ABORT')
  lines[i]='    init: true\\n'
 else:lines.insert(ix+1,'    init: true\\n')
 return ''.join(lines),True
def compose_cmd(project,filepath):
 return [DOCKER,'compose','--project-directory',str(ROOT),'-p',project,'-f',str(filepath)]
def config(project,filepath):
 value=invoke(compose_cmd(project,filepath)+['config','--format','json'],timeout=50)
 obj=json.loads(value)
 if 'services' not in obj or SERVICE not in obj['services']:
  raise RuntimeError('PUBLIC_MONITOR_NOT_IN_RENDERED_COMPOSE')
 return obj
def count_zombies():
 num=0
 for x in pathlib.Path('/proc').iterdir():
  if not x.name.isdigit():continue
  try:
   s=(x/'status').read_text('utf-8',errors='replace')
   for line in s.splitlines():
    if line.startswith('State:') and line.partition(':')[2].strip().startswith('Z'):
     num+=1;break
  except OSError:pass
 return num
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ('check','apply'):
  raise RuntimeError('USE_CHECK_OR_APPLY')
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not pathlib.Path(DOCKER).is_file() or not COMPOSE.is_file() or COMPOSE.is_symlink():
  raise RuntimeError('DOCKER_OR_COMPOSE_UNAVAILABLE')
 before=inspect()
 original=COMPOSE.read_text('utf-8')
 proposed,changed=patch_yaml(original)
 if before['init'] is True and not changed:
  emit(status='P21_ALREADY_ENABLED',container=CONTAINER,init=True,channel_sends=0)
  return
 if before['init'] is True and changed:
  raise RuntimeError('RUNNING_INIT_ALREADY_TRUE_BUT_COMPOSE_DIFFERS')
 tmp_path=None
 try:
  fd,tmp_path=tempfile.mkstemp(prefix='.p21_compose_',suffix='.yaml',dir=str(ROOT))
  with os.fdopen(fd,'w') as f:
   f.write(proposed);f.flush();os.fsync(f.fileno())
  old_cfg=config(before['project'],COMPOSE)
  new_cfg=config(before['project'],tmp_path)
  expected=copy.deepcopy(old_cfg)
  expected['services'][SERVICE]['init']=True
  if new_cfg!=expected:
   raise RuntimeError('COMPOSE_DIFF_NOT_LIMITED_TO_ONE_INIT_FIELD_ABORT')
  if not changed:raise RuntimeError('NO_FILE_DIFF_BUT_RUNTIME_INIT_DISABLED_ABORT')
  if sys.argv[1]=='check':
   emit(status='P21_PREFLIGHT_PASS',container=CONTAINER,project=before['project'],
       pid=before['pid'],init_before=before['init'],planned_change='services.public-monitor.init: true',
       scoped_service_restart_required=True,channel_sends=0)
   return
  before_again=inspect()
  if before_again['id']!=before['id'] or before_again['pid']!=before['pid']:
   raise RuntimeError('CONTAINER_CHANGED_DURING_PREFLIGHT_ABORT')
  backup=ROOT/('compose.yaml.p21_backup_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
  with os.fdopen(os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
   f.write(original);f.flush();os.fsync(f.fileno())
  os.chmod(tmp_path,stat.S_IMODE(COMPOSE.stat().st_mode))
  os.chown(tmp_path,COMPOSE.stat().st_uid,COMPOSE.stat().st_gid)
  os.replace(tmp_path,str(COMPOSE));tmp_path=None
  old_zombies=count_zombies()
  try:
   # --no-build prevents surprise image rebuild, --no-deps avoids dependency restarts.
   invoke(compose_cmd(before['project'],COMPOSE)+['up','-d','--no-deps','--no-build','--force-recreate',SERVICE],timeout=120)
  except Exception:
   # Restore source if Docker Compose failed. Container may still need manual review.
   restore_fd,restore_tmp=tempfile.mkstemp(prefix='.p21_restore_',dir=str(ROOT))
   with os.fdopen(restore_fd,'w') as f:
    f.write(original);f.flush();os.fsync(f.fileno())
   os.chmod(restore_tmp,stat.S_IMODE(COMPOSE.stat().st_mode))
   os.chown(restore_tmp,COMPOSE.stat().st_uid,COMPOSE.stat().st_gid)
   os.replace(restore_tmp,str(COMPOSE))
   raise RuntimeError('RECREATE_FAILED_COMPOSE_RESTORED_REVIEW_CONTAINER_STATE')
  time.sleep(5)
  # Freshly recreated container receives new ID; separate inspection without old id assumption.
  a=json.loads(invoke([DOCKER,'inspect',CONTAINER]))[0]
  l=a['Config'].get('Labels') or {}
  after={'id':a['Id'][:12],'pid':a['State'].get('Pid'),
       'running':a['State'].get('Running'),'init':a['HostConfig'].get('Init'),
       'image':a['Config'].get('Image'),'service':l.get('com.docker.compose.service')}
  if not (after['running'] and after['init'] is True and after['id']!=before['id'][:12]
    and after['image']==IMAGE and after['service']==SERVICE):
   raise RuntimeError('POST_RESTART_VERIFICATION_FAILED_COMPOSE_BACKUP_'+backup.name)
  emit(status='P21_INIT_REAPER_ENABLED',container=CONTAINER,
       old_id=before['id'][:12],new_id=after['id'],init_before=before['init'],init_after=after['init'],
       new_pid=after['pid'],zombies_before=old_zombies,zombies_after=count_zombies(),
       backup=backup.name,compose_change='services.public-monitor.init: true',
       other_services_requested=False,telegram_touched=False,channel_sends=0)
 finally:
  if tmp_path and os.path.exists(tmp_path):os.unlink(tmp_path)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='P21_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
    channel_sends=0);sys.exit(1)
