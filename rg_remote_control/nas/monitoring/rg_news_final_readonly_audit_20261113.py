#!/usr/bin/env python3
"""RG NEWS2 safe read-only acceptance report. No network, no writes, no Telegram API."""
import ast, hashlib, json, sqlite3, subprocess, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
REL=OP/'news_rg_stability_releases_v1'
PY=OP/'tools/python-3.15.2/bin/python3.15'
TARGET=OP/'news_rg_stable5_operational_gate_v1.py'
RESULTS={}
def record(k,v): RESULTS[k]=v
def stamp(n):
 try: return datetime.fromtimestamp(float(n),timezone.utc).isoformat()
 except Exception: return 'UNKNOWN'
def load(p):
 if not p.is_file() or p.is_symlink(): return {}
 try: return json.loads(p.read_text(encoding='utf-8'))
 except (ValueError,OSError,UnicodeError): return {}
def age(n):
 try: return max(0,round((time.time()-float(n))/60,1))
 except Exception: return None
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def report():
 record('time_utc',stamp(time.time()))
 record('python_version',sys.version.split()[0])
 pin=load(REL/'pinned_release_v1.json')
 manifest=pin.get('files',{}) if isinstance(pin.get('files'),dict) else {}
 mismatches=[]
 for name,expected in manifest.items():
  p=OP/name
  if not isinstance(name,str) or '/' in name or not p.is_file() or p.is_symlink() or sha(p)!=expected:
   mismatches.append(name)
 record('pinned_release_version',pin.get('version','UNKNOWN'))
 record('pinned_module_count',len(manifest))
 record('pinned_hash_mismatches',mismatches[:24])
 record('patch_present',TARGET.is_file() and 'p.returncode not in (0,1,2)' in TARGET.read_text())
 record('pinned_archive_exists',bool(pin.get('last_known_good_archive')) and Path(pin['last_known_good_archive']).is_file())
 record('prior_archive_exists',bool(pin.get('prior_archive')) and Path(pin['prior_archive']).is_file())
 record('release_guard_last_status',load(REL/'guard_last_tick.json').get('status','UNKNOWN'))
 record('release_guard_last_age_min',age(load(REL/'guard_last_tick.json').get('checked_at')))
 record('release_integrity_pass',len(manifest)==18 and not mismatches and RESULTS['patch_present'] and RESULTS['pinned_archive_exists'])

 try:
  p=subprocess.run([str(PY),str(OP/'news_rg_stability_healthcheck_v1.py'),'check'],text=True,capture_output=True,timeout=30)
  health=json.loads(p.stdout)
  record('health_exit_code',p.returncode)
  record('health_status',health.get('status','UNKNOWN'))
  record('health_alert_codes',[x.get('code','UNKNOWN') for x in health.get('alerts',[]) if isinstance(x,dict)])
  for key in ('source','private','staging','public','dsm'):
   part=health.get(key,{})
   if not isinstance(part,dict): part={}
   record(key+'_status',part.get('status','UNKNOWN'))
   if key=='source':
    record('source_count',part.get('source_count'))
    record('source_last_scan_age_min',part.get('last_scan_age_min'))
   if key=='private':
    for k in ('confirmed_private_cards','waiting_for_human_count','pending_cards','latest_private_age_min'):
     v=part.get(k)
     if isinstance(v,(int,float,str,bool)) or v is None:record('private_'+k,v)
   if key=='public':
    for k in ('confirmed_publications','uncertain_sends'):
     v=part.get(k)
     if isinstance(v,(int,float,str,bool)) or v is None:record('public_'+k,v)
 except Exception as e:record('healthcheck_error',type(e).__name__)

 try:
  con=sqlite3.connect('file:'+str(BASE/'news.sqlite3')+'?mode=ro',uri=True,timeout=3)
  con.execute('PRAGMA query_only=ON')
  record('db_candidate_count',con.execute('SELECT COUNT(*) FROM candidates').fetchone()[0])
  record('db_candidate_status',dict(con.execute('SELECT status,COUNT(*) FROM candidates GROUP BY status').fetchall()))
  record('db_latest_candidate_created',con.execute('SELECT MAX(created_at) FROM candidates').fetchone()[0])
  record('db_latest_event',con.execute('SELECT MAX(at) FROM events').fetchone()[0])
  record('db_moderation_dispatch_states',dict(con.execute('SELECT state,COUNT(*) FROM moderation_dispatch GROUP BY state').fetchall()))
  record('db_photo_dispatch_states',dict(con.execute('SELECT state,COUNT(*) FROM rg_news2_photo_dispatch GROUP BY state').fetchall()))
  record('db_rg_v35_publication_rows',con.execute('SELECT COUNT(*) FROM rg_v35_publications').fetchone()[0])
  con.close()
 except Exception as e:record('db_error',type(e).__name__)

 directory=OP/'news_rg_private_multipart_receipts_v1'
 counts=Counter(); uncertain=[]
 if directory.is_dir() and not directory.is_symlink():
  for f in directory.glob('*.json'):
   if f.is_symlink():continue
   v=load(f)
   if not isinstance(v,dict):counts['INVALID']+=1;continue
   status=v.get('status','UNKNOWN')
   if not isinstance(status,str):status='INVALID'
   counts[status]+=1
   if status in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY'):
    uncertain.append({'status':status,'modified_utc':stamp(f.stat().st_mtime),'error_class':str(v.get('error_class','UNKNOWN'))[:32]})
 record('receipt_status_counts',dict(counts))
 record('uncertain_receipts',uncertain[:10])
 callback=load(OP/'news_rg_callback_scheduled_state_v1.json')
 record('callback_status',callback.get('status','UNKNOWN'))
 record('callback_age_min',age(callback.get('checked_at_utc')))
 backup=load(BASE/'autonomous_backups_v1/last_success.json')
 record('backup_age_hours',round((time.time()-float(backup['at']))/3600,2) if isinstance(backup.get('at'),(int,float)) else None)
 export=load(Path('/volume1/docker/RG_TELEGRAM_NEWS_EXPORT/rg_news_health_public.json'))
 record('sanitized_export_age_min',age(export.get('generated_at_unix')))
 record('sanitized_export_schema',export.get('schema','UNKNOWN'))
 record('sanitized_export_secrets_flag',export.get('contains_secrets','UNKNOWN'))
 record('telegram_api_calls_by_this_audit',0)
 record('publications_by_this_audit',0)
 record('public_channel_runtime_verified',False)

if __name__=='__main__':
 try:report()
 except Exception as e:record('audit_error',type(e).__name__)
 print(json.dumps(RESULTS,ensure_ascii=False,sort_keys=True,indent=2))
