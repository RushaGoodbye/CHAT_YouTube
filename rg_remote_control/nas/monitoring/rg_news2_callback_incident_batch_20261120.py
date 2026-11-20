#!/usr/bin/env python3
"""Read-only NEWS2 callback health/owner diagnostics. No Telegram requests."""
import ast,datetime,json,os,pathlib,re,sys,time,hashlib
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=ROOT/'operator'
P=O/'news_rg_poll_moderation_v1.py'
EXPECTED='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
NOW=time.time()
NAMES=['news_rg_continuous_callback_v1.py','news_rg_callback_scheduled_tick_v1.py',
       'rg_news2_p31_guarded_callback_once.py','news_rg_autonomous_health_v1.py',
       'news_rg_stable5_operational_gate_v1.py','news_rg_poll_moderation_v1.py',
       'news_rg_health_control_v1.py']
PAT=re.compile(r'(?i)(stale|callback|handoff|last_success|last_update|last_seen|heartbeat|halted|error_class|lock|poll_pass|poll_failed)')
SECRET=re.compile(r'(?i)(token|secret|password|api.key|authorization|https?://|chat_id|user_id|photo_url)')
def processes():
 rows=[]
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdecimal():continue
  try:
   args=[x.decode('utf8','replace') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
   names=[pathlib.Path(x).name for x in args if x.endswith('.py') and
     ('callback' in x or 'p31_guarded' in x)]
   if names:rows.append({'pid':int(p.name),'scripts':names})
  except (OSError,PermissionError):pass
 return rows[:30]
def script_info():
 result=[]
 for name in NAMES:
  p=O/name
  if not p.is_file() or p.is_symlink():
   result.append({'name':name,'present':False});continue
  try:
   src=p.read_text('utf8');t=ast.parse(src)
   f=[{'name':x.name,'line':x.lineno} for x in t.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))]
   flags={k:[i for i,line in enumerate(src.splitlines(),1) if k in line][:10] for k in
      ('TELEGRAM_CALLBACK_STALE','STABLE5_TELEGRAM_CALLBACK_STALE','HANDOFF_BLOCKED',
       'getUpdates','webhook','last_success','last_seen','LOCK')}
   result.append({'name':name,'functions':f[:40],
     'signals':{k:v for k,v in flags.items() if v}})
  except Exception as e:result.append({'name':name,'error':type(e).__name__})
 return result
def log_info():
 candidates=[]
 for base in (O,ROOT,O/'news_rg_stability_releases_v1'):
  if not base.is_dir():continue
  for p in base.iterdir():
   if not any(x in p.name.lower() for x in ('callback','handoff','health','stable5')):continue
   if p.suffix not in ('.log','.json','.txt','.state'):continue
   try:
    if p.is_symlink() or p.stat().st_size>2000000:continue
    lines=p.read_text('utf8','replace').splitlines()[-100:]
    hits=[line.strip()[:220] for line in lines if PAT.search(line) and not SECRET.search(line)
          and len(line)<260 and not line.lstrip().startswith(('def ','import ','from '))]
    candidates.append({'file':p.name,'age_seconds':round(NOW-p.stat().st_mtime),
      'last_status_lines':hits[-5:]})
   except (OSError,UnicodeError):pass
 return sorted(candidates,key=lambda x:x['age_seconds'])[:24]
def state_info():
 results=[]
 for name in ('news_rg_autonomous_health_v1.json','news_rg_health_control_state_v1.json',
              'news_rg_callback_scheduled_tick_v1.json','news_rg_continuous_callback_v1.json'):
  for base in (O,ROOT):
   p=base/name
   try:
    if not p.is_file() or p.is_symlink():continue
    data=json.loads(p.read_text('utf8'))
    if not isinstance(data,dict):continue
    values={}
    for k,v in data.items():
     if not PAT.search(k) or SECRET.search(k):continue
     if isinstance(v,(bool,int,float)) or v is None:values[k]=v
     elif isinstance(v,str) and len(v)<120 and not SECRET.search(v):values[k]=v
    results.append({'file':name,'age_seconds':round(NOW-p.stat().st_mtime),'status_fields':values})
   except (OSError,ValueError):pass
 return results
def main():
 sched=ROOT/'rg_news_dsm_tick.sh'
 lines=sched.read_text('utf8','replace').splitlines() if sched.is_file() else []
 result={'status':'RG_NEWS2_CALLBACK_STALE_BATCH_DIAG',
 'v6_sha_match':P.is_file() and hashlib.sha256(P.read_bytes()).hexdigest()==EXPECTED,
 'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'processes':processes(),'script_contract':script_info(),
 'state':state_info(),'recent_logs':log_info(),
 'scheduler_callback_lines':[i for i,s in enumerate(lines,1) if 'callback' in s.lower()],
 'telegram_calls':0,'getUpdates_calls':0,'publications':0,'restarts':0,'files_changed':0}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'RG_NEWS2_CALLBACK_DIAG_SAFE_STOP','error':type(e).__name__,
   'telegram_calls':0,'publications':0},ensure_ascii=False));sys.exit(2)
