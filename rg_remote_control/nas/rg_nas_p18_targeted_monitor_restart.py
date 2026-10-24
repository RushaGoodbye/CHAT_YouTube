#!/usr/bin/env python3
"""P18 targeted NAS zombie remediation: restart ONLY rg-public-monitor after strict owner verification.
No other container touched. No Telegram API, database, crontab or publishing changes.
"""
import datetime,json,os,pathlib,re,subprocess,sys,time
NAME='rg-public-monitor'
EXPECT_ID='070a14c49034'
EXPECT_IMAGE='rg_monitor-public-monitor'
DOCKER='/usr/local/bin/docker'
def run(args,timeout=40):
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout)
 if p.returncode:raise RuntimeError('COMMAND_FAILED_'+str(args[1] if len(args)>1 else 'UNKNOWN'))
 return p.stdout.strip()
def stat(pid):
 try:
  d={}
  for row in pathlib.Path('/proc/'+str(pid)+'/status').read_text().splitlines():
   if ':' in row:
    k,v=row.split(':',1)
    if k in ('Name','State','PPid'):d[k]=v.strip()
  return d
 except Exception:return {}
def zombies():
 total=0;parents={};children={}
 for item in pathlib.Path('/proc').iterdir():
  if not item.name.isdigit():continue
  x=stat(item.name)
  if x.get('State','').startswith('Z'):
   total+=1
   key=x.get('PPid','?');parents[key]=parents.get(key,0)+1
   n=x.get('Name','?');children[n]=children.get(n,0)+1
 return {'total':total,'top_parents':sorted(
    [{'pid':int(k),'count':v,'name':stat(k).get('Name','exited')} for k,v in parents.items() if k.isdigit()],
    key=lambda x:-x['count'])[:5],'kinds':children}
def inspect():
 # Inspect only exact single container; output is programmatic and never prints config secrets.
 s=run([DOCKER,'inspect','--format','{{.Id}}|{{.Name}}|{{.State.Pid}}|{{.State.Running}}|{{.Config.Image}}|{{.RestartCount}}',NAME])
 fields=s.split('|')
 if len(fields)!=6:raise RuntimeError('UNEXPECTED_DOCKER_INSPECT')
 full,name,pid,running,image,restarts=fields
 if not full.startswith(EXPECT_ID) or name!='/'+NAME or image!=EXPECT_IMAGE or running!='true':
  raise RuntimeError('CONTAINER_ID_NAME_IMAGE_OR_RUNNING_MISMATCH_ABORT')
 if not pid.isdigit() or int(pid)<2:raise RuntimeError('BAD_HOST_PID_ABORT')
 if stat(pid).get('Name')!='uvicorn':raise RuntimeError('CONTAINER_INIT_NOT_UVICORN_ABORT')
 return {'id':full[:12],'name':name,'pid':int(pid),'image':image,'restart_count':restarts}
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not pathlib.Path(DOCKER).is_file():raise RuntimeError('DOCKER_MISSING')
 before=inspect();zb=zombies()
 owned=next((x['count'] for x in zb['top_parents'] if x['pid']==before['pid']),0)
 if owned<10:raise RuntimeError('ZOMBIE_PARENT_NOT_DOMINANT_REVIEW_FIRST')
 # Local journal before action, no Docker logs to avoid credentials in outputs.
 audit=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
 if not audit.is_dir() or audit.is_symlink():raise RuntimeError('AUDIT_DIR_NOT_SAFE')
 record={'status':'P18_BEFORE','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'container':before,'zombies':zb,'owned':owned}
 audit_path=audit/('P18_RESTART_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
 with os.fdopen(os.open(str(audit_path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
  json.dump(record,f)
  f.flush();os.fsync(f.fileno())
 restarted=run([DOCKER,'restart','--time','10',NAME],timeout=75)
 if restarted!=NAME:raise RuntimeError('UNEXPECTED_RESTART_REPLY')
 time.sleep(4)
 after=inspect()
 if after['pid']==before['pid']:raise RuntimeError('INIT_PID_UNCHANGED_AFTER_RESTART')
 zafter=zombies()
 time.sleep(10)
 later=zombies()
 success=later['total']<zb['total']
 result={'status':'P18_RESTART_OK' if success else 'P18_RESTARTED_ZOMBIES_NOT_REDUCED',
  'target':NAME,'restarted_only_target':True,
  'before':{'pid':before['pid'],'total_zombies':zb['total'],'target_zombies':owned},
  'after':{'pid':after['pid'],'total_zombies':zafter['total']},
  'after_10sec':{'total_zombies':later['total'],'new_zombies':later['total']-zafter['total']},
  'audit_file':str(audit_path),'other_containers_modified':False,'telegram_api_calls':0,
  'channel_sends':0,'publication_gate_changed':False,'next':'Observe growth and inspect monitor source if zombies recur'}
 print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'P18_BLOCKED_OR_FAILED','reason':str(e) if isinstance(e,RuntimeError) else type(e).__name__,
  'manual_review_required':True},ensure_ascii=False),flush=True);sys.exit(1)
