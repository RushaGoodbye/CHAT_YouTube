#!/usr/bin/env python3
"""P20 read-only monitor source and subprocess lifecycle audit.
Reads /app/monitor.py from specific Docker container using docker cp TAR;
does not execute inside it or alter any container. Sensitive source literals omitted.
"""
import ast,datetime,io,json,os,pathlib,subprocess,sys,tarfile
D='/usr/local/bin/docker';NAME='rg-public-monitor';PREFIX='070a14c49034';IMAGE='rg_monitor-public-monitor'
def run(args,seconds=25):
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=seconds)
 if p.returncode:raise RuntimeError('DOCKER_'+args[1]+'_FAILED')
 return p.stdout
def inspect():
 t='{{.Id}}|{{.Name}}|{{.State.Running}}|{{.Config.Image}}'
 v=run([D,'inspect','--format',t,NAME]).decode('utf-8','replace').strip().split('|')
 if len(v)!=4 or not v[0].startswith(PREFIX) or v[1]!='/'+NAME or v[2]!='true' or v[3]!=IMAGE:
  raise RuntimeError('UNEXPECTED_CONTAINER_ID_OR_IMAGE')
 return v[0][:12]
def code_from_container():
 # docker cp does not spawn processes inside the monitored container.
 raw=run([D,'cp',NAME+':/app/monitor.py','-'])
 if len(raw)>8*1024*1024:raise RuntimeError('MONITOR_SOURCE_TOO_LARGE')
 with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as tar:
  members=[x for x in tar.getmembers() if x.isfile()]
  if len(members)!=1:raise RuntimeError('UNEXPECTED_TAR_MEMBERS')
  file=tar.extractfile(members[0])
  code=file.read(2*1024*1024).decode('utf-8')
 return code
def exprlabel(n):
 if isinstance(n,ast.Name):return n.id
 if isinstance(n,ast.Attribute):return exprlabel(n.value)+'.'+n.attr
 return type(n).__name__
def scope(node):
 p=node
 return type(p).__name__+'@'+str(getattr(p,'lineno',0))
def audit_code(s):
 tree=ast.parse(s)
 funcs=[]
 for x in ast.walk(tree):
  if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)):
   funcs.append({'function':x.name,'start_line':x.lineno,'async':isinstance(x,ast.AsyncFunctionDef)})
 markers=['subprocess','Popen','create_subprocess','os.system','os.popen','multiprocessing','headless_shell','docker','wait','communicate','poll','check_output','run','shell','asyncio']
 matches=[]
 lines=s.splitlines()
 for x in ast.walk(tree):
  if not isinstance(x,ast.Call):continue
  name=exprlabel(x.func)
  if not any(k in name for k in ('subprocess','Popen','create_subprocess','os.system','os.popen','docker','wait','communicate','check_output','run','call','exec')):
   continue
  f=next((y.name for y in ast.walk(tree) if isinstance(y,(ast.FunctionDef,ast.AsyncFunctionDef))
   and y.lineno<=x.lineno<=getattr(y,'end_lineno',y.lineno) ),'<module>')
  matches.append({'line':x.lineno,'call':name[:100],'function':f,
   'keywords':[k.arg for k in x.keywords if k.arg and k.arg in ('timeout','shell','stdout','stderr','check','capture_output','start_new_session','text','close_fds')],
   'awaited':False})
 markers_count={k:sum(1 for line in lines if k.lower() in line.lower()) for k in markers if any(k.lower() in line.lower() for line in lines)}
 return {'source_lines':len(lines),'functions':funcs[:65],
  'subprocess_and_wait_calls':sorted(matches,key=lambda x:x['line'])[:100],
  'markers_found':markers_count}
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not pathlib.Path(D).is_file():raise RuntimeError('DOCKER_MISSING')
 cid=inspect()
 raw=run([D,'inspect','--format','{{json .Config.Labels}}',NAME]).decode('utf-8','replace')
 try:labels=json.loads(raw)
 except Exception:labels={}
 compose={'working_dir':str(labels.get('com.docker.compose.project.working_dir',''))[:150],
          'config_files':str(labels.get('com.docker.compose.project.config_files',''))[:200],
          'service':str(labels.get('com.docker.compose.service',''))[:80]}
 try:source=audit_code(code_from_container());status='P20_MONITOR_SOURCE_AUDITED'
 except Exception as e:source={'error':str(e) if isinstance(e,RuntimeError) else type(e).__name__};status='P20_MONITOR_SOURCE_UNAVAILABLE'
 output={'status':status,'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'container':NAME,'id':cid,'compose':compose,'source':source,
  'changes':0,'docker_exec':0,'no_secrets_or_code_literals_output':True,
  'other_containers_touched':False,'telegram_untouched':True}
 print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'P20_BLOCKED','reason':str(e) if isinstance(e,RuntimeError) else type(e).__name__},ensure_ascii=False))
  sys.exit(1)
