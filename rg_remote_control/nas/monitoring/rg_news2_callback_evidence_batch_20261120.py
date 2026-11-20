#!/usr/bin/env python3
"""RG NEWS2 callback evidence batch, read-only.

Compares callback freshness health logic with current state/receipts.
Does not import bot code, access Telegram API, run getUpdates, or edit files.
Does not output private chat IDs, tokens, raw Telegram updates, or message bodies.
"""
import ast,datetime,hashlib,json,os,pathlib,re,sys,time
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=ROOT/'operator'
NOW=time.time()
PIN='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
CODE=('news_rg_autonomous_health_v1.py','news_rg_stable5_operational_gate_v1.py',
      'news_rg_health_control_v1.py','news_rg_callback_scheduled_tick_v1.py',
      'rg_news2_p31_guarded_callback_once.py','news_rg_continuous_callback_v1.py')
TERMS=('TELEGRAM_CALLBACK_STALE','STABLE5_TELEGRAM_CALLBACK_STALE',
       'last_success','callback_age','callback','HANDOFF_BLOCKED',
       'getUpdates','heartbeat','last_notice','getoff','putoff')
SECRETS=re.compile(r'(?i)(https?://|token|secret|password|api_key|authorization|[0-9]{8,12}:[A-Za-z0-9_-]{30,})')
def safe_metadata(p):
 if not p.is_file() or p.is_symlink():return None
 st=p.stat()
 return {'basename':p.name,'mtime_utc':datetime.datetime.fromtimestamp(st.st_mtime,datetime.timezone.utc).isoformat(),
         'age_seconds':round(NOW-st.st_mtime),'bytes':st.st_size}
def file_bytes(p,maxsize=1500000):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>maxsize:return None
 return p.read_bytes()
def clean_value(value,depth=0):
 if depth>5:return '[depth limit]'
 if isinstance(value,bool) or value is None:return value
 if isinstance(value,(int,float)):return value
 if isinstance(value,str):
  if len(value)>110 or SECRETS.search(value):return '[redacted]'
  if re.fullmatch(r'\d{5,}',value):return '[numeric ID redacted]'
  return value
 if isinstance(value,list):return [clean_value(x,depth+1) for x in value[:8]]
 if isinstance(value,dict):
  return {k:clean_value(v,depth+1) for k,v in value.items()
          if not SECRETS.search(k) and k.lower() not in
          ('message','text','caption','photo','video','chat','user','username','first_name','last_name','url','raw_update','update','token')
          and not re.search(r'(?i)(user|moderator|sender|recipient|chat|phone|email|message|file_id|update_id|private_id)',k)
          and re.search(r'(?i)(status|callback|success|last|age|heartbeat|poll|offset|error|warning|alert|stale|owner|handoff|checked|update)',k)}
 return type(value).__name__
def sources():
 out=[]
 for name in CODE:
  p=O/name
  raw=file_bytes(p,150000)
  if raw is None:
   out.append({'file':name,'status':'MISSING'});continue
  try:
   s=raw.decode('utf8');tree=ast.parse(s)
   rows=[]
   lines=s.splitlines()
   for i,line in enumerate(lines,1):
    if any(term in line for term in TERMS) and not SECRETS.search(line):
     # Preserve only non-secret conditional structure and source line numbers.
     if any(word in line for word in ('if ','age','get(','mtime','time.time','last_success','CALLBACK_STALE','error_class','HANDOFF_BLOCKED')):
      rows.append({'line':i,'expression':line.strip()[:170]})
   out.append({'file':name,'status':'PARSED','logic_lines':rows[:32]})
  except Exception as e:out.append({'file':name,'status':'SOURCE_PARSE_FAILED','error':type(e).__name__})
 return out
def states():
 out=[]
 for parent in (ROOT,O,O/'news_rg_stability_releases_v1'):
  if not parent.is_dir():continue
  for p in parent.iterdir():
   low=p.name.lower()
   if not any(k in low for k in ('callback','handoff','health','stable5','poll_private_pilot_receipt')):continue
   if p.suffix!='.json':continue
   raw=file_bytes(p,180000)
   if raw is None:continue
   try:
    obj=json.loads(raw.decode('utf8'))
    if not isinstance(obj,dict):continue
    item=safe_metadata(p)
    item['fields']=clean_value(obj)
    # Report only recent and key state files, no raw updates.
    if NOW-p.stat().st_mtime<14400 or p.name in ('news_rg_stable5_operational_status_v1.json',
        'news_rg_callback_scheduled_state_v1.json','rg_poll_private_pilot_receipt.json'):
     out.append(item)
   except (ValueError,UnicodeError,OSError):continue
 return sorted(out,key=lambda x:x['age_seconds'])[:30]
def handoffs():
 # Check last 1h files without exposing contents. Count only recent file timestamps.
 paths=[]
 for parent in (ROOT,O):
  if not parent.is_dir():continue
  for p in parent.iterdir():
   if p.is_file() and 'updates_handoff_guarded' in p.name and p.suffix=='.json':
    try:
     if p.stat().st_mtime>NOW-3600:paths.append(p)
    except OSError:pass
 ages=[round(NOW-p.stat().st_mtime) for p in paths]
 return {'recent_hour_count':len(paths),'newest_age_seconds':min(ages) if ages else None,
         'oldest_age_seconds':max(ages) if ages else None,
         'contains_test_message_1183':None,
         'note':'Handoff files intentionally not read; Telegram update contents are private'}
def sessions():
 found=[]
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdecimal():continue
  try:
   items=[pathlib.Path(x.decode('utf8','replace')).name for x in (p/'cmdline').read_bytes().split(b'\0') if x]
   names=[x for x in items if x in ('news_rg_continuous_callback_v1.py','rg_news2_p31_guarded_callback_once.py',
        'news_rg_callback_scheduled_tick_v1.py')]
   if names:found.append({'pid':int(p.name),'modules':names})
  except (OSError,PermissionError):pass
 return found
def main():
 poll=O/'news_rg_poll_moderation_v1.py'
 v6=bool(poll.is_file() and hashlib.sha256(poll.read_bytes()).hexdigest()==PIN)
 out={'status':'RG_NEWS2_CALLBACK_EVIDENCE_BATCH_READONLY',
      'v6_integrity': 'PASS' if v6 else 'FAIL',
      'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'callback_processes':sessions(),'monitoring_source_logic':sources(),
      'recent_state':states(),'recent_handoffs':handoffs(),
      'telegram_calls':0,'getUpdates_calls':0,'publications':0,'restarts':0,'files_modified':0,
      'real_callback_ack_confirmed':False,'cloudflare_live_verified':False}
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as exc:
  print(json.dumps({'status':'RG_NEWS2_CALLBACK_EVIDENCE_SAFE_STOP',
    'error':type(exc).__name__,'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
