#!/usr/bin/env python3
"""NEWS RG + existing Gatus integration inventory, strictly read-only.

Reports only safe wiring metadata; no YAML content, tokens, URLs, bot IDs,
environment variables, commands, or mounted secret paths are printed.
No changes to DSM/Gatus/Observer/Telegram and no new processes.
"""
import json,os,re,sys,shutil,pathlib,subprocess,datetime,time
GATUS='rg-nas-gatus';OBSERVER='rg-nas-gatus-observer'
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
TICK=ROOT/'rg_news_dsm_tick.sh'
def sh(cmd):
 try:
  res=subprocess.run(cmd,capture_output=True,timeout=9)
  if res.returncode:return None
  return res.stdout.decode('utf8','replace')[:200000]
 except (OSError,subprocess.TimeoutExpired):return None
def section(text,key):
 lines=text.splitlines()
 start=None
 for i,line in enumerate(lines):
  if re.match(r'^'+re.escape(key)+r'\s*:',line):
   start=i+1;break
 if start is None:return ''
 result=[]
 for line in lines[start:]:
  if line.strip() and not line[0].isspace() and not line.lstrip().startswith('#'):break
  result.append(line)
 return '\n'.join(result)
def safe_yaml_inventory(text):
 external=section(text,'external-endpoints')
 blocks=[];current=[]
 for line in external.splitlines():
  if re.match(r'^[ \t]{2}-\s+name\s*:',line):
   if current:blocks.append('\n'.join(current))
   current=[line]
  elif current:current.append(line)
 if current:blocks.append('\n'.join(current))
 result=[]
 for block in blocks:
  # Only print normalized name/group when they are known-safe short labels;
  # YAML anchors, aliases, substitutions and token-like strings stay hidden.
  raw_name=re.search(r'(?m)^\s*-\s*name\s*:\s*(.+?)\s*$',block)
  raw_group=re.search(r'(?m)^\s*group\s*:\s*(.+?)\s*$',block)
  def normal(match):
   if not match:return 'UNKNOWN'
   v=match.group(1).split(' #',1)[0].strip().strip('\'"')
   return v if re.fullmatch(r'[a-zA-Z0-9 _.-]{1,50}',v) else 'HIDDEN'
  name=normal(raw_name);group=normal(raw_group)
  interval=re.search(r'(?m)^\s+interval\s*:\s*["\']?(\d+[smh])',block)
  result.append({'name':name,'group':group,
    'heartbeat_interval':interval.group(1) if interval else 'UNKNOWN',
    'token_present':bool(re.search(r'(?m)^\s+token\s*:\s*\S+',block)),
    'alerts_defined':bool(re.search(r'(?m)^\s+alerts\s*:',block))})
 return {'external_endpoints':result,
  'global_alerting_section':bool(re.search(r'(?m)^alerting\s*:',text)),
  'gatus_health_endpoint_configured':any('news' in x['name'].lower() and 'rg' in x['name'].lower() for x in result)}
def info(container_name,exe):
 raw=sh([exe,'inspect',container_name])
 if raw is None:return {'inspect_ok':False}
 try:
  v=json.loads(raw)[0]
  state=v.get('State') or {}
  mounts=v.get('Mounts') or []
  results={'inspect_ok':True,'running':state.get('Running') is True,
     'bind_mount_count':sum(m.get('Type')=='bind' for m in mounts),
     'restart_policy':str((v.get('HostConfig') or {}).get('RestartPolicy',{}).get('Name',''))[:30]}
  if container_name==GATUS:
   found=False
   for m in mounts:
    if m.get('Type')!='bind' or '/config' not in str(m.get('Destination','')).lower():continue
    p=pathlib.Path(str(m.get('Source','')))
    opts=[p] if p.is_file() else [p/'config.yaml',p/'config.yml',p/'gatus'/'config.yaml',p/'gatus'/'config.yml']
    for item in opts:
     try:
      if item.is_symlink() or not item.is_file() or item.stat().st_size>500000:continue
      data=item.read_text(encoding='utf8')
      results.update(safe_yaml_inventory(data))
      found=True;break
     except (OSError,UnicodeError):continue
    if found:break
   results['config_readable']=found
  else:
   files=[]
   for m in mounts:
    if m.get('Type')!='bind':continue
    p=pathlib.Path(str(m.get('Source','')))
    if p.is_file() and p.suffix=='.py':files.append(p)
    elif p.is_dir() and 'observer' in str(m.get('Destination','')).lower():
     try:
      files.extend(q for q in p.glob('*.py') if q.is_file() and not q.is_symlink())
     except OSError:pass
   files=files[:15]
   patterns={'python_source_readable':False,'gatus_push_code_found':False,
     'news_rg_healthcheck_referenced':False,'runs_external_commands':False}
   for p in files:
    try:
     if p.stat().st_size>200000:continue
     text=p.read_text('utf8')
     patterns['python_source_readable']=True
     patterns['gatus_push_code_found']|=bool('external?success=' in text or 'external?' in text or 'api/v1/endpoints' in text)
     patterns['news_rg_healthcheck_referenced']|=bool('news_rg_stability_healthcheck' in text)
     patterns['runs_external_commands']|=bool('subprocess.' in text or 'os.system(' in text)
    except (OSError,UnicodeError):pass
   results.update(patterns)
  return results
 except (ValueError,TypeError,IndexError):
  return {'inspect_ok':False}
def task_status():
 cli=next((p for p in ('/usr/syno/bin/synoschedtask','/usr/syno/sbin/synoschedtask')
          if pathlib.Path(p).is_file()),None)
 if not cli:return {'id':4,'enabled':'UNKNOWN'}
 raw=sh([cli,'--get','id=4'])
 if raw is None:return {'id':4,'enabled':'UNKNOWN'}
 m=re.search(r'(?im)^\s*State\s*:\s*\[\s*(enabled|disabled)\s*\]',raw)
 return {'id':4,'enabled':'YES' if m and m.group(1).lower()=='enabled' else
         'NO' if m else 'UNKNOWN','correct_script_found':'rg_news_dsm_tick' in raw}
def tick_status():
 try:
  if TICK.is_symlink() or not TICK.is_file() or TICK.stat().st_size>50000:raise OSError
  s=TICK.read_text('utf8')
  return {'available':True,'three_news_rg_hooks':all(key in s for key in
    ('news_rg_safe_schedule_v2.py','news_rg_private_dispatch_schedule_v1.py',
     'news_rg_publication_schedule_v1.py')),
   'stability_check_hook':('news_rg_stability_healthcheck_v1.py' in s),
   'gatus_news_rg_push_hook':('news_rg_gatus' in s)}
 except (OSError,UnicodeError):return {'available':False}
def run():
 if os.geteuid()!=0:raise RuntimeError('ROOT_REQUIRED')
 exe=shutil.which('docker') or ('/usr/local/bin/docker' if pathlib.Path('/usr/local/bin/docker').is_file() else None)
 if not exe:return {'status':'NO_DOCKER'}
 g=info(GATUS,exe);o=info(OBSERVER,exe)
 has_alerts=g.get('global_alerting_section') is True
 news=g.get('gatus_health_endpoint_configured') is True
 return {'schema':'NEWS_RG_GATUS_INTEGRATION_INVENTORY_V1',
   'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'read_only':True,'telegram_calls':0,'ai_calls':0,'gatus_push_calls':0,
   'created_schedules':0,'created_pollers':0,'production_changes':0,
   'gatus':g,'existing_observer':o,'dsm':task_status(),'dsm_tick':tick_status(),
   'integration_state':'ALREADY_CONFIGURED' if news and (o.get('news_rg_healthcheck_referenced') or tick_status().get('gatus_news_rg_push_hook'))
      else 'REQUIRES_CONTROLLED_CONFIG_INTEGRATION',
   'notification_state':'GATUS_ALERTS_CONFIGURED' if has_alerts else 'NO_GATUS_ALERT_PROVIDER',
   'proposal':'REUSE_EXISTING_DSM_TASK_OR_OBSERVER; DO_NOT_CREATE_NEW_POLLERS'}
def selftest():
 text='external-endpoints:\n  - name: nas-heartbeat\n    group: services\n    token: SECRET_SECRET\n    heartbeat:\n      interval: 40m\n  - name: second\n    group: services\n    token: SECRET_2\n'
 result=safe_yaml_inventory(text)
 assert len(result['external_endpoints'])==2
 assert result['external_endpoints'][0]['heartbeat_interval']=='40m'
 assert result['external_endpoints'][1]['alerts_defined'] is False
 assert 'SECRET' not in json.dumps(result)
 assert section('endpoints:\n  - name: hello\nexternal-endpoints:\n  - name: abc\n','external-endpoints').strip()=='- name: abc'
 print('NEWS_RG_GATUS_INTEGRATION_INVENTORY_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['inspect']:print(json.dumps(run(),ensure_ascii=False,sort_keys=True,indent=2))
  else:raise RuntimeError('INVALID_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','error_type':type(e).__name__,
    'read_only':True,'production_changes':0},ensure_ascii=False))
  sys.exit(2)
