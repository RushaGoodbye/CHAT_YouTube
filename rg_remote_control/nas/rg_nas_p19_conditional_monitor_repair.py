#!/usr/bin/env python3
"""P19: identify current zombie parent and restart ONLY confirmed rg-public-monitor if still broken.
Two checks 10 seconds apart, no Telegram polling or publishing; safe no-op if cleared.
"""
import datetime,json,os,pathlib,subprocess,sys,time
NAME='rg-public-monitor'
ID_PREFIX='070a14c49034'
IMAGE='rg_monitor-public-monitor'
DOCKER='/usr/local/bin/docker'
AUDIT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
def emit(d):print(json.dumps(d,ensure_ascii=False,indent=2),flush=True)
def run(args,timeout=40):
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout)
 if p.returncode:raise RuntimeError('COMMAND_FAILED_'+str(args[1] if len(args)>1 else 'UNKNOWN'))
 return p.stdout.strip()
def stat(pid):
 try:
  d={}
  for line in pathlib.Path('/proc/'+str(pid)+'/status').read_text().splitlines():
   if ':' in line:
    k,v=line.split(':',1)
    if k in ('Name','State','PPid'):d[k]=v.strip()
  return d
 except (OSError,ValueError):return {}
def inspect():
 t='{{.Id}}|{{.Name}}|{{.State.Pid}}|{{.State.Running}}|{{.Config.Image}}|{{.RestartCount}}'
 f=run([DOCKER,'inspect','--format',t,NAME]).split('|')
 if len(f)!=6:raise RuntimeError('UNEXPECTED_DOCKER_INSPECT')
 cid,name,pid,running,image,restarts=f
 if not cid.startswith(ID_PREFIX) or name!='/'+NAME or image!=IMAGE:
  raise RuntimeError('CONTAINER_IDENTITY_CHANGED_NO_ACTION')
 if running!='true' or not pid.isdigit() or int(pid)<2:
  raise RuntimeError('CONTAINER_NOT_RUNNING_NO_ACTION')
 if stat(pid).get('Name')!='uvicorn':raise RuntimeError('INIT_NOT_UVICORN_NO_ACTION')
 cg=pathlib.Path('/proc/'+str(pid)+'/cgroup').read_text(errors='replace')
 if cid not in cg:raise RuntimeError('PID_CGROUP_MISMATCH_NO_ACTION')
 return {'id':cid[:12],'pid':int(pid),'restarts':restarts}
def zombie_counts():
 total=0;parents={}
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit():continue
  s=stat(p.name)
  if s.get('State','').startswith('Z'):
   total+=1;ppid=s.get('PPid','')
   if ppid.isdigit():parents[int(ppid)]=parents.get(int(ppid),0)+1
 return total,parents
def audit(d):
 if not AUDIT.is_dir() or AUDIT.is_symlink():return 'AUDIT_DIRECTORY_UNAVAILABLE'
 ts=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
 p=AUDIT/('P19_MONITOR_'+ts+'.json')
 with os.fdopen(os.open(str(p),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
  json.dump(d,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 return str(p)
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not pathlib.Path(DOCKER).is_file():raise RuntimeError('DOCKER_MISSING')
 before=inspect();t1,p1=zombie_counts()
 time.sleep(10)
 after=inspect();t2,p2=zombie_counts()
 result={'status':'P19_PRECHECK','container':NAME,'id':after['id'],
  'old_pid':before['pid'],'current_pid':after['pid'],'sample_seconds':10,
  'before':{'zombies_total':t1,'owned':p1.get(before['pid'],0)},
  'after':{'zombies_total':t2,'owned':p2.get(after['pid'],0)},
  'old_restart_count':before['restarts'],'current_restart_count':after['restarts'],
  'other_containers_touched':False,'telegram_untouched':True,'channel_sends':0}
 if before['pid']!=after['pid']:
  result['status']='P19_AUTO_RESTART_ALREADY_HAPPENED_NO_ACTION'
 elif min(p1.get(before['pid'],0),p2.get(after['pid'],0))<10:
  result['status']='P19_ZOMBIE_BACKLOG_CLEARED_NO_RESTART'
 else:
  verify=inspect();t3,p3=zombie_counts()
  if verify['pid']!=after['pid'] or p3.get(verify['pid'],0)<10:
   result['status']='P19_CONDITION_CHANGED_NO_RESTART'
  else:
   result['pre_restart_zombies']=p3.get(verify['pid'],0)
   reply=run([DOCKER,'restart','--time','10',NAME],timeout=75)
   if reply!=NAME:raise RuntimeError('RESTART_RESPONSE_UNEXPECTED')
   time.sleep(4)
   final=inspect();tf,pf=zombie_counts()
   result['new_pid']=final['pid']
   result['post_restart']={'zombies_total':tf,'owned':pf.get(final['pid'],0)}
   result['status']='P19_TARGET_RESTARTED_VERIFIED' if final['pid']!=verify['pid'] else 'P19_RESTARTED_PID_UNCHANGED_REVIEW'
 result['audit_file']=audit(result);emit(result)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit({'status':'P19_BLOCKED','reason':str(e) if isinstance(e,RuntimeError) else type(e).__name__,'channel_sends':0})
  sys.exit(1)
