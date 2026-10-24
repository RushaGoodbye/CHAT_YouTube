#!/usr/bin/env python3
"""NAS targeted zombie-parent identification: process ancestry, Docker membership,
cgroup PID limits and package/command identity. Read-only. Never prints env,
credentials or full command arguments.
"""
import collections,datetime,json,os,pathlib,re,subprocess,sys,time
P=pathlib.Path('/proc')
def txt(p,limit=8192):
 try:return pathlib.Path(p).read_text('utf-8',errors='replace')[:limit]
 except Exception:return ''
def status(pid):
 s=txt(P/str(pid)/'status',8192);d={}
 for line in s.splitlines():
  if ':' in line:
   k,v=line.split(':',1)
   if k in ('Name','State','PPid','Threads','VmRSS','Uid','NSpid'):d[k]=v.strip()
 return d
def sanitized_argv(pid):
 try:
  b=(P/str(pid)/'cmdline').read_bytes()[:8192]
  v=[s.decode('utf-8','replace') for s in b.split(b'\0') if s]
 except Exception:return []
 res=[]
 for s in v[:8]:
  if not s:continue
  if s.startswith('-'):
   if re.fullmatch(r'-{1,2}[a-zA-Z0-9_-]{1,30}',s):res.append(s)
   continue
  if '/' in s or '\\' in s:
   s=os.path.basename(s.rstrip('/'))
  # Retain only python module specs or plain process names, never credential/url.
  if re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.:-]{0,90}',s):
   if not any(t in s.lower() for t in ('token','password','secret','key=')):res.append(s)
 return res
def pids():
 return [int(x.name) for x in P.iterdir() if x.name.isdigit()]
def chain(pid,maximum=15):
 seen=set();out=[]
 for _ in range(maximum):
  if pid in seen or pid<1:break
  seen.add(pid);s=status(pid)
  if not s:
   out.append({'pid':pid,'exited':True});break
  rec={'pid':pid,'ppid':int(s.get('PPid','0')),'name':s.get('Name'),'state':s.get('State'),
       'threads':s.get('Threads'),'memory':s.get('VmRSS'),'argv_safe':sanitized_argv(pid)}
  try:rec['executable']=os.path.basename(os.readlink(str(P/str(pid)/'exe')))
  except Exception:pass
  try:rec['cwd_basename']=os.path.basename(os.readlink(str(P/str(pid)/'cwd')).rstrip('/'))
  except Exception:pass
  out.append(rec)
  if pid==1:break
  pid=rec['ppid']
 return out
def run(cmd,timeout=18):
 try:
  p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout)
  return (p.returncode,p.stdout)
 except Exception:return (99,'')
def docker_containers():
 binary=next((p for p in ('/usr/local/bin/docker','/usr/bin/docker') if pathlib.Path(p).is_file()),None)
 if not binary:return {'available':False}
 code,out=run([binary,'ps','-q','--no-trunc'])
 if code!=0:return {'available':True,'ps_ok':False}
 ids=[s.strip() for s in out.splitlines() if re.fullmatch(r'[0-9a-f]{12,64}',s.strip())][:100]
 if not ids:return {'available':True,'ps_ok':True,'running':0,'entries':[]}
 fmt='{{.Id}}|{{.Name}}|{{.State.Pid}}|{{.Config.Image}}|{{.HostConfig.RestartPolicy.Name}}'
 code,out=run([binary,'inspect','--format',fmt]+ids,timeout=25)
 if code!=0:return {'available':True,'ps_ok':True,'inspect_ok':False,'running':len(ids)}
 c=[]
 for line in out.splitlines():
  v=line.split('|')
  if len(v)==5:
   try:p=int(v[2])
   except Exception:continue
   c.append({'id':v[0][:12],'name':v[1].lstrip('/')[:100],'init_host_pid':p,'image':v[3][:130],'restart_policy':v[4][:40]})
 return {'available':True,'ps_ok':True,'inspect_ok':True,'running':len(ids),'entries':c}
def main():
 if os.geteuid()!=0:
  print(json.dumps({'status':'BLOCKED','reason':'SUDO_REQUIRED'}));sys.exit(1)
 active=pids()
 parent_counter=collections.Counter()
 children=collections.Counter()
 for pid in active:
  s=status(pid)
  if s.get('State','').startswith('Z'):
   parent_counter[s.get('PPid','0')]+=1
   children[s.get('Name','?')]+=1
 suspect=parent_counter.most_common(1)
 if not suspect:print(json.dumps({'status':'P17_NO_ZOMBIES','readonly':True}));return
 target=int(suspect[0][0]);ancestry=chain(target)
 docker=docker_containers()
 for c in docker.get('entries',[]):
  # Container init ancestor is strong evidence, never trust matching command name alone.
  c['owns_target']=(c['init_host_pid'] in [x['pid'] for x in ancestry])
 report={'status':'P17_TARGET_IDENTIFIED_READ_ONLY','timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'target_pid':target,'zombies_owned':suspect[0][1],
   'all_zombies':sum(parent_counter.values()),
   'zombie_types':dict(children.most_common(5)),
   'ancestry':ancestry,'docker':docker,
   'cgroup_target':txt(P/str(target)/'cgroup',2500).splitlines()[:8],
   'target_limits':txt(P/str(target)/'limits',3500).splitlines()[:15],
   'target_ns_pid':None,
   'action':'NO_PROCESS_TERMINATION_OR_RESTART',
   'telegram_unchanged':True,'api_calls':0}
 try:report['target_ns_pid']=os.readlink(str(P/str(target)/'ns/pid'))
 except Exception:pass
 # Keep stdout concise when Docker hosts many unrelated containers.
 owns=[x for x in docker.get('entries',[]) if x.get('owns_target')]
 report['docker']={k:v for k,v in docker.items() if k!='entries'}
 report['docker']['owning_containers']=owns
 report['docker']['candidate_containers']=[x for x in docker.get('entries',[]) if
     any(t in x['name'].lower() for t in ('mcp','telegram','browser','youtube','auto','rg-','rg_'))][:25]
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
