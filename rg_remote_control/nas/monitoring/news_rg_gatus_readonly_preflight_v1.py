#!/usr/bin/env python3
"""Discover existing local Gatus monitoring integration, read-only.

Does not read or print credentials. Does not change NAS/docker/Gatus/DSM,
schedule, Telegram callbacks, production code, or Gatus configuration.
The only network request is HTTP GET to 127.0.0.1:18080.
"""
import sys,os,re,json,time,pathlib,shutil,subprocess,urllib.request,urllib.error

GATUS_URL='http://127.0.0.1:18080/'
TASK_ID='4'
def cmd(argv,timeout=10):
 try:
  r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=timeout)
  return r.returncode,r.stdout.decode('utf-8','replace')[:250000]
 except (OSError,subprocess.TimeoutExpired):return -1,''
def gatus_http():
 try:
  with urllib.request.urlopen(
      urllib.request.Request(GATUS_URL,headers={'User-Agent':'NEWS-RG-READONLY-PREFLIGHT/1'}),
      timeout=5) as r:
   return {'reachable':r.status==200,'http_status':r.status,'checked_url':'127.0.0.1:18080'}
 except urllib.error.HTTPError as e:
  return {'reachable':False,'http_status':e.code,'checked_url':'127.0.0.1:18080'}
 except (urllib.error.URLError,TimeoutError,OSError):
  return {'reachable':False,'http_status':None,'checked_url':'127.0.0.1:18080'}
def config_info(container):
 ret={'visible_on_host':False,'configured_http_endpoints':False,
      'has_external_endpoints_section':False,'has_alerting_section':False,
      'host_config_candidates':0}
 mounts=container.get('Mounts') or []
 candidates=[]
 for mount in mounts:
  if not isinstance(mount,dict) or mount.get('Type')!='bind':continue
  src=pathlib.Path(str(mount.get('Source','')))
  dest=str(mount.get('Destination','')).lower()
  # Only explicitly Gatus config destination. Never scan unrelated mounts.
  if '/config' not in dest:continue
  if src.is_symlink():continue
  if src.is_file() and src.suffix.lower() in ('.yaml','.yml'):
   candidates.append(src)
  elif src.is_dir():
   candidates.extend([src/'config.yaml',src/'config.yml'])
   # Docker compose deployments may mount a parent config directory.
   candidates.extend([src/'gatus'/'config.yaml',src/'gatus'/'config.yml'])
 ret['host_config_candidates']=len(candidates)
 for p in candidates:
  try:
   if p.is_symlink() or not p.is_file() or p.stat().st_size>500000:continue
   data=p.read_text('utf-8')
   ret['visible_on_host']=True
   # Report presence of structural keys only; never print config text.
   for name,key in [('configured_http_endpoints','endpoints'),
                    ('has_external_endpoints_section','external-endpoints'),
                    ('has_alerting_section','alerting')]:
    if re.search(r'(?m)^'+re.escape(key)+r'\s*:',data):
     ret[name]=True
  except (OSError,UnicodeError):continue
 return ret
def docker_info():
 exe=shutil.which('docker')
 if not exe and pathlib.Path('/usr/local/bin/docker').is_file():
  exe='/usr/local/bin/docker'
 if not exe:return {'available':False}
 rc,out=cmd([exe,'ps','-a','--format','{{.Names}}'])
 if rc:return {'available':True,'query_ok':False}
 names=[s.strip() for s in out.splitlines() if 'gatus' in s.lower()]
 if not names:return {'available':True,'query_ok':True,'gatus_containers':[]}
 reports=[]
 for name in names[:5]:
  rc,raw=cmd([exe,'inspect',name])
  if rc:reports.append({'name':name,'inspect_ok':False});continue
  try:
   data=json.loads(raw)
   item=data[0]
   state=item.get('State') or {}
   conf=item.get('Config') or {}
   reports.append({'name':str(item.get('Name','')).lstrip('/'),
     'inspect_ok':True,'running':state.get('Running') is True,
     'image':str(conf.get('Image',''))[:120],
     'config':config_info(item)})
  except (ValueError,IndexError,TypeError):
   reports.append({'name':name,'inspect_ok':False})
 return {'available':True,'query_ok':True,'gatus_containers':reports}
def dsm_task():
 cli=next((p for p in ('/usr/syno/bin/synoschedtask','/usr/syno/sbin/synoschedtask')
          if pathlib.Path(p).is_file()),None)
 if not cli:return {'status':'CLI_UNAVAILABLE','task_id':4}
 rc,out=cmd([cli,'--get','id='+TASK_ID])
 if rc:return {'status':'TASK_QUERY_FAILED','task_id':4,'exit_code':rc}
 # Do not print command, owner, task parameters, environment, or schedule text.
 text=out.lower()
 present='rg_news_dsm_tick' in text
 yes=bool(re.search(r'(?m)^\s*(?:enabled|enable|is_enabled)\s*[:=]\s*(?:true|1|yes)\b',text))
 no=bool(re.search(r'(?m)^\s*(?:enabled|enable|is_enabled)\s*[:=]\s*(?:false|0|no)\b',text))
 return {'status':'TASK_FOUND' if present else 'TASK_QUERY_RETURNED',
         'task_id':4,'rg_news_tick_named':present,
         'enabled':'YES' if yes and not no else 'NO' if no and not yes else 'UNKNOWN'}
def run():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 h=gatus_http();d=docker_info();task=dsm_task()
 configs=[x.get('config',{}) for x in d.get('gatus_containers',[]) if x.get('inspect_ok')]
 return {
  'schema':'NEWS_RG_GATUS_READONLY_PREFLIGHT_V1',
  'read_only':True,'changes':0,'telegram_calls':0,'ai_calls':0,
  'new_processes_or_pollers':0,'scheduled_tasks_created':0,
  'gatus_http':h,'docker':d,'dsm_task_4':task,
  'config_visible':any(c.get('visible_on_host') for c in configs),
  'external_endpoints_already_declared':any(c.get('has_external_endpoints_section') for c in configs),
  'gatus_alert_section_present':any(c.get('has_alerting_section') for c in configs),
  'recommended_next_step':
      'REVIEW_EXISTING_GATUS_CONFIG_BEFORE_ANY_CHANGE'
       if h.get('reachable') and configs
       else 'GATUS_NOT_CONFIRMED_OR_CONFIG_NOT_VISIBLE'
 }
def selftest():
 assert re.search(r'(?m)^external-endpoints\s*:','endpoints:\nexternal-endpoints:\n')
 assert not re.search(r'(?m)^external-endpoints\s*:','# external-endpoints:\n')
 assert GATUS_URL.startswith('http://127.0.0.1:')
 print('NEWS_RG_GATUS_READONLY_PREFLIGHT_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['inspect']:print(json.dumps(run(),indent=2,sort_keys=True,ensure_ascii=False))
  else:raise RuntimeError('EXPECTED_SELFTEST_OR_INSPECT')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','error_type':type(e).__name__,
      'read_only':True,'changes':0,'telegram_calls':0},ensure_ascii=False))
  sys.exit(2)
