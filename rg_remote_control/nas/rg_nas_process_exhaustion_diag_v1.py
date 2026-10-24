#!/usr/bin/env python3
"""NAS process exhaustion forensic, no modifications or external API calls."""
import collections,datetime,json,os,pathlib,subprocess,time
def read(p,lim=4096):
 try:return pathlib.Path(p).read_text('utf-8',errors='replace')[:lim]
 except Exception:return ''
def snap():
 proc=pathlib.Path('/proc');names={};z=[]
 for p in proc.iterdir():
  if not p.name.isdigit():continue
  s=read(p/'status',8192)
  if not s:continue
  kv={}
  for line in s.splitlines():
   if ':' in line:
    k,v=line.split(':',1)
    if k in ('Name','State','PPid','Threads'):kv[k]=v.strip()
  if not kv:continue
  names[p.name]=kv
  if kv.get('State','').startswith('Z'):
   cg=read(p/'cgroup',1500)
   group=''
   for line in cg.splitlines():
    sp=line.split(':',2)
    if len(sp)==3 and sp[2]:
     group=sp[2].split('/')[-1] or '/'
     break
   z.append({'pid':int(p.name),'ppid':kv.get('PPid'),'name':kv.get('Name','?'),
             'cgroup':group[:60]})
 pc=collections.Counter(x.get('Name','?') for x in names.values())
 parents=collections.Counter(x['ppid'] for x in z)
 groups=collections.Counter(x['cgroup'] for x in z)
 plist=[]
 for pid,n in parents.most_common(8):
  d=names.get(pid,{})
  plist.append({'pid':int(pid),'zombies':n,'parent_present':bool(d),
    'parent_name':d.get('Name','MISSING'),'parent_state':d.get('State','UNKNOWN'),
    'parent_threads':d.get('Threads'),'zombie_samples':[x['pid'] for x in z if x['ppid']==pid][:4]})
 return {'processes':len(names),'zombies':len(z),
  'zombie_names':dict(collections.Counter(x['name'] for x in z).most_common(8)),
  'zombie_parents':plist,'zombie_cgroups':dict(groups.most_common(10)),
  'headless_shell_total':pc.get('headless_shell',0),'sshd_total':pc.get('sshd',0)}
def run(a):
 try:
  p=subprocess.run(a,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=8)
  return {'exit':p.returncode,'stdout':p.stdout[:1600]}
 except Exception as e:return {'error':type(e).__name__}
def main():
 start=snap();time.sleep(10);end=snap()
 diag={'status':'NAS_PROCESS_EXHAUSTION_DIAG_PASS','sample_seconds':10,
   'now_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'start':start,'end':end,
   'zombie_delta':end['zombies']-start['zombies'],
   'process_delta':end['processes']-start['processes'],
   'pid_max':read('/proc/sys/kernel/pid_max').strip(),
   'threads_max':read('/proc/sys/kernel/threads-max').strip(),
   'cgroup_root_pid_current':read('/sys/fs/cgroup/pids.current').strip(),
   'cgroup_root_pid_max':read('/sys/fs/cgroup/pids.max').strip(),
   'cgroup_root_v1_pid_current':read('/sys/fs/cgroup/pids/pids.current').strip(),
   'cgroup_root_v1_pid_max':read('/sys/fs/cgroup/pids/pids.max').strip(),
   'uptime':read('/proc/uptime').strip(),
   'moderation_untouched':True,'telegram_calls':0,'changes':0}
 print(json.dumps(diag,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
