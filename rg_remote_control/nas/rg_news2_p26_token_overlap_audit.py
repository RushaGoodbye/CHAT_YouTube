#!/usr/bin/env python3
"""RG News2 P26: read-only token overlap and competing callback source audit.
Never print secrets; no Telegram API, cron, DB, or container mutations.
"""
import datetime,json,os,pathlib,re,subprocess,sys
ROOT=pathlib.Path('/volume1/docker')
NEWS=ROOT/'RG_SECRETS'/'rg_telegram_bot_token'
D='/usr/local/bin/docker'
SOURCES=['RG_MONITOR/app/main.py','RG_ALERTS_DEPLOY/cloudflare-alerts/src/telegram-moderation.js',
'RG_ALERTS_DEPLOY/cloudflare-alerts/src/manual-import.js','RG_TELEGRAM_NEWS_2/rg_moderation.py']
CONFIG=['RG_ALERTS_DEPLOY/cloudflare-alerts/wrangler.toml',
'RG_ALERTS_DEPLOY/cloudflare-alerts/wrangler.jsonc','RG_ALERTS_DEPLOY/cloudflare-alerts/wrangler.json',
'RG_ALERTS_DEPLOY/cloudflare-alerts/.dev.vars','RG_ALERTS_DEPLOY/cloudflare-alerts/.env',
'RG_MONITOR/.env','RG_MONITOR/compose.yaml']
def read(rel):
 p=ROOT/rel
 try:
  if not p.is_file() or p.is_symlink() or p.stat().st_size>330000:return None
  return p.read_text('utf-8',errors='replace')
 except Exception:return None
def proc(cmd):
 try:
  p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
       universal_newlines=True,timeout=30)
  return p.returncode,p.stdout
 except Exception:return 98,''
def envrefs(s):
 return sorted(set(re.findall(r'(?:env\.|process\.env\.)([A-Z][A-Z0-9_]{3,65})',s)))
def inspect_source(rel):
 s=read(rel)
 if s is None:return {'path':rel,'exists':False}
 lines=s.splitlines()
 matches=[]
 for n,line in enumerate(lines,1):
  if 'getUpdates' not in line or line.lstrip().startswith(('//','#','*')):continue
  neighborhood='\n'.join(lines[max(0,n-20):min(len(lines),n+20)])
  matches.append({'line':n,'possible_bindings':[k for k in envrefs(neighborhood) if 'TOKEN' in k or 'BOT' in k]})
 return {'path':rel,'matches':matches[:12],
         'bot_secret_variable_names':[k for k in envrefs(s) if 'TOKEN' in k or 'BOT' in k][:35]}
def containers(secret):
 rc,out=proc([D,'ps','-q','--no-trunc'])
 if rc:return {'available':False}
 ids=[x for x in out.splitlines() if re.fullmatch(r'[a-f0-9]{12,64}',x)]
 if not ids:return {'running':0,'entries':[]}
 rc,out=proc([D,'inspect']+ids)
 if rc:return {'running':len(ids),'inspect_error':True}
 rows=[]
 try:all_data=json.loads(out)
 except Exception:return {'inspect_json_error':True}
 for x in all_data:
  name=str(x.get('Name','')).lstrip('/')
  env=x.get('Config',{}).get('Env') or []
  cand=[]
  for line in env:
   if '=' not in line:continue
   k,v=line.split('=',1)
   if 'TOKEN' in k.upper() and ('BOT' in k.upper() or 'TELEGRAM' in k.upper()):
    cand.append({'key':k,'matches_news2_bot_token':v==secret if ':' in v else None})
  rows.append({'name':name,'token_checks':cand})
 return {'running':len(all_data),'entries':rows}
def local_configs(secret):
 out=[]
 for rel in CONFIG:
  s=read(rel)
  if s is None:continue
  vars_found=sorted(set(re.findall(r'\b(?:TELEGRAM|BOT|MODERATION)[A-Z0-9_]{3,60}',s)))
  checks=[]
  for line in s.splitlines():
   m=re.match(r'^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$',line)
   if not m:continue
   k=m.group(1)
   if 'TOKEN' not in k or not ('TELEGRAM' in k or 'BOT' in k):continue
   v=m.group(2).strip().strip('"').strip("'")
   if len(v)<20 or v.startswith('$'):continue
   checks.append({'key':k,'matches_news2_bot_token':v==secret})
  out.append({'path':rel,'secret_binding_names':vars_found[:30],
      'local_literal_token_checks':checks[:20],
      'has_cron_or_triggers':bool(re.search(r'\bcrons\b|\btriggers\b',s))})
 return out
def main():
 if os.geteuid()!=0:
  print(json.dumps({'status':'P26_BLOCKED','reason':'SUDO_REQUIRED'}));return
 try:secret=NEWS.read_text('utf-8').strip()
 except Exception:
  print(json.dumps({'status':'P26_BLOCKED','reason':'TOKEN_FILE_UNREADABLE'}));return
 if not re.fullmatch(r'\d{6,14}:[A-Za-z0-9_-]{20,}',secret):
  print(json.dumps({'status':'P26_BLOCKED','reason':'TOKEN_FORMAT_UNEXPECTED'}));return
 report={'status':'NEWS2_P26_TOKEN_OVERLAP_AUDIT_READONLY',
  'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'sources':[inspect_source(x) for x in SOURCES],
  'active_containers':containers(secret),
  'local_config':local_configs(secret),
  'cloudflare_secret_unverifiable_from_nas':True,
  'telegram_api_calls':0,'publication_changes':0,'file_changes':0,'channel_sends':0}
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
