#!/usr/bin/env python3
"""News2 P23: read-only LIVE Telegram callback ownership inventory.
Does not call Telegram, Cloudflare, change files or restart anything.
"""
import datetime,json,os,pathlib,re,subprocess,sys
ROOT=pathlib.Path('/volume1/docker')
FILES=[
 'RG_TELEGRAM_NEWS_2/rg_moderation.py',
 'RG_MONITOR/app/main.py',
 'RG_ALERTS_DEPLOY/cloudflare-alerts/src/telegram-moderation.js',
 'RG_ALERTS_DEPLOY/cloudflare-alerts/src/calendar-entry.js',
 'RG_ALERTS_DEPLOY/cloudflare-alerts/src/manual-import.js',
 'RG_AUDIT_WORK/repo/telegram_video_moderation.py']
CRON='/etc/crontab'
DOCKER='/usr/local/bin/docker'
def run(args,timeout=15):
 try:
  p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout)
  return p.returncode,p.stdout
 except Exception:return 99,''
def script_flags(relative):
 p=ROOT/relative
 d={'path':relative,'exists':p.is_file() and not p.is_symlink()}
 if not d['exists']:return d
 try:
  if p.stat().st_size>350000: d['too_large']=True;return d
  lines=p.read_text('utf-8',errors='replace').splitlines()
 except Exception as e:d['read_error']=type(e).__name__;return d
 rows=[]
 last_function='<module>'
 patfun=re.compile(r'^\s*(?:async\s+)?(?:def\s+|function\s+|(?:export\s+)?(?:async\s+)?function\s+)([A-Za-z_][A-Za-z0-9_]*)')
 for idx,ln in enumerate(lines,1):
  m=patfun.match(ln)
  if m:last_function=m.group(1)
  if 'getUpdates' in ln and not ln.lstrip().startswith(('#','//','*')):
   rows.append({'line':idx,'scope_guess':last_function,
    'https_request_nearby':any('fetch(' in x or 'https.request' in x or 'api.telegram.org' in x for x in lines[max(0,idx-10):min(len(lines),idx+8)]),
    'as_string':bool(re.search(r'[\x27\x22\x60]getUpdates[\x27\x22\x60]',ln))})
 d['getupdates_references']=rows[:24];d['total_matches']=len(rows)
 d['code_mentions_callback_query']=any('callback_query' in x for x in lines)
 return d
def compose():
 if not pathlib.Path(DOCKER).is_file():return {'docker_available':False}
 rc,out=run([DOCKER,'ps','-q','--no-trunc'])
 if rc:return {'docker_available':True,'ps_ok':False}
 ids=[x.strip() for x in out.splitlines() if re.fullmatch(r'[0-9a-f]{12,64}',x.strip())]
 if not ids:return {'docker_available':True,'running':0}
 fmt='{{.Name}}|{{.State.Pid}}|{{.Config.Image}}|{{json .Mounts}}|{{json .Config.Labels}}'
 rc,out=run([DOCKER,'inspect','--format',fmt]+ids,timeout=25)
 if rc:return {'docker_available':True,'running':len(ids),'inspect_ok':False}
 rows=[]
 for line in out.splitlines():
  a=line.split('|',4)
  if len(a)!=5:continue
  try:
   mounts=json.loads(a[3] or '[]') or []
   labels=json.loads(a[4] or '{}') or {}
  except Exception:continue
  related=[]
  for m in mounts:
   source=m.get('Source') or ''
   if any(t in source for t in ('RG_MONITOR','RG_ALERTS_DEPLOY','RG_TELEGRAM_NEWS_2','RG_AUDIT_WORK')):
    related.append({'source':source[:140],'destination':str(m.get('Destination',''))[:140]})
  rows.append({'name':a[0].lstrip('/'),'pid':a[1],'image':a[2][:130],
    'service':str(labels.get('com.docker.compose.service',''))[:90],
    'related_mounts':related[:12]})
 return {'docker_available':True,'running':len(rows),'containers':rows}
def crons():
 p=pathlib.Path(CRON)
 if not p.is_file():return []
 data=p.read_text('utf-8',errors='replace')
 matched=[]
 for line in data.splitlines():
  if line.startswith('#') or not line.strip():continue
  if any(x in line.lower() for x in ('telegram','rg_news2','monitor','alerts')):
   tags=[key for key in ('getUpdates','callback','monitor','alerts','rg_news2','telegram') if key.lower() in line.lower()]
   fields=line.split(maxsplit=6)
   matched.append({'time':fields[:5],'tags':tags,'mentions_python':'.py' in line,
     'mentions_shell':'.sh' in line})
 return matched[:100]
def process_markers():
 out=[]
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   c=(p/'cmdline').read_bytes()[:4096].decode('utf-8','replace').replace('\0',' ')
  except Exception:continue
  if any(x in c.lower() for x in ('getupdates','telegram_video_moderation','cloudflare-alerts','rg_moderation','rg_news2')):
   out.append({'pid':int(p.name),'command_type':'python' if 'python' in c.lower() else 'node' if 'node' in c.lower() else 'other',
     'matches':[x for x in ('getupdates','telegram_video_moderation','cloudflare-alerts','rg_moderation','rg_news2') if x in c.lower()]})
 return out[:45]
def main():
 if os.geteuid()!=0:
  print(json.dumps({'status':'P23_BLOCKED','reason':'SUDO_REQUIRED'}));sys.exit(1)
 report={'status':'NEWS2_P23_LIVE_POLLER_INVENTORY','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'relevant_source_files':[script_flags(x) for x in FILES],
   'runtime_containers':compose(),'cron_candidates':crons(),
   'process_name_hits':process_markers(),
   'interpretation':'File presence alone does NOT prove an active polling owner.',
   'telegram_calls':0,'cron_changes':0,'channel_sends':0,'file_changes':0}
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
