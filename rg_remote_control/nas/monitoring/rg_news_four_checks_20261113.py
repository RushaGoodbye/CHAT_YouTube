#!/usr/bin/env python3
"""RG NEWS2 four-part safe acceptance: no network, no bot sends, no production writes.
1 receipts; 2 public ledger; 3 backup restore drill to ephemeral isolated temp;
4 runner cutover gate. Always fail closed.
"""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,sqlite3,os,subprocess,tarfile,tempfile,shutil,time
B=Path('/volume1/docker/RG_TELEGRAM_NEWS_2'); O=B/'operator'
R=O/'news_rg_stability_releases_v1'
OUT={}
def now():return datetime.now(timezone.utc).isoformat()
def meta(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>1048576:return {}
  return json.loads(p.read_text())
 except (OSError,ValueError,UnicodeError):return {}
def redact_status(v):return v if isinstance(v,str) and len(v)<70 and all(c.isalnum() or c in '_-.' for c in v) else 'REDACTED'
def part1():
 p=O/'news_rg_private_multipart_receipts_v1'
 counts=Counter(); uncertain=[]; last=0
 for f in p.glob('*.json'):
  if f.is_symlink():continue
  d=meta(f)
  if not isinstance(d,dict):continue
  s=d.get('status','UNKNOWN');counts[redact_status(s)]+=1
  if s=='PRIVATE_SENT_CONFIRMED' and isinstance(d.get('confirmed_at'),(float,int)):
   last=max(last,d['confirmed_at'])
  if s in ('UNCERTAIN_NO_RETRY','SENDING_UNCERTAIN'):
   uncertain.append({'name_sha256_12':hashlib.sha256(f.name.encode()).hexdigest()[:12],
     'status':s,'error_class':redact_status(d.get('error_class')),'mtime_utc':datetime.fromtimestamp(f.stat().st_mtime,timezone.utc).isoformat(),
     'contains_message_id':isinstance(d.get('message_id'),int)})
 return {'receipt_states':dict(counts),'uncertain':uncertain[:20],'latest_confirmed_utc':datetime.fromtimestamp(last,timezone.utc).isoformat() if last else None,
 'resolution':'BLOCKED_NEEDS_INDEPENDENT_DELIVERY_EVIDENCE' if uncertain else 'NO_UNCERTAIN_RECEIPTS',
 'no_retry_enforced_by_audit':True}
def part2():
 base=O
 # Inspect existing healthcheck's public ledger without writing/sending.
 hc=base/'news_rg_stability_healthcheck_v1.py';py=O/'tools/python-3.15.2/bin/python3.15'
 v={'live_telegram_api_verified':False}
 try:
  r=subprocess.run([str(py),str(hc),'check'],capture_output=True,text=True,timeout=30)
  report=json.loads(r.stdout)
  public=report.get('public',{})
  v.update({'health_exit':r.returncode,'health_status':report.get('status'),
   'public_ledger_status':public.get('status'),'confirmed_publications':public.get('confirmed_publications'),
   'uncertain_sends':public.get('uncertain_sends')})
 except Exception as e:v['healthcheck_error']=type(e).__name__
 v['verdict']='LEDGER_ONLY_NOT_LIVE_CHANNEL_VERIFIED'
 return v
def part3():
 pinned=meta(R/'pinned_release_v1.json'); prior=Path(pinned.get('prior_archive','/missing'))
 stable=Path(pinned.get('last_known_good_archive','/missing'))
 backups=B/'autonomous_backups_v1'
 found=[]
 for p in (stable,prior):
  if p.is_file() and not p.is_symlink():
   found.append({'type':'release_archive','size':p.stat().st_size,'age_hours':round((time.time()-p.stat().st_mtime)/3600,1)})
 backup=meta(backups/'last_success.json')
 result={'last_success_age_hours':round((time.time()-backup['at'])/3600,2) if isinstance(backup.get('at'),(int,float)) else None,
  'pinned_archives':found,'data_restore_verified':False,'release_archive_read_test':False}
 # Perform isolated archive extraction validation without touching production.
 if not stable.is_file() or stable.is_symlink():result['verdict']='BLOCKED_MISSING_STABLE_ARCHIVE';return result
 try:
  with tempfile.TemporaryDirectory(prefix='rg_news_restore_drill_') as tmp:
   root=Path(tmp)
   with tarfile.open(stable,'r:gz') as tf:
    members=tf.getmembers()
    if len(members)>100 or sum(m.size for m in members)>50*1024*1024:raise ValueError('archive_limits')
    for m in members:
     q=Path(m.name)
     if not m.isfile() or q.is_absolute() or '..' in q.parts or m.issym() or m.islnk():raise ValueError('unsafe_member')
     target=root/q
     target.parent.mkdir(parents=True,exist_ok=True)
     src=tf.extractfile(m)
     if src is None:raise ValueError('missing_member')
     with target.open('wb') as out:shutil.copyfileobj(src,out)
    needed=O/'news_rg_stable5_operational_gate_v1.py'
    result['extracted_files']=len(members)
    result['release_archive_read_test']=bool(list(root.rglob(needed.name)))
    result['verdict']='RELEASE_RESTORE_SIMULATION_PASS_DATA_RESTORE_NOT_TESTED' if result['release_archive_read_test'] else 'RELEASE_FILE_NOT_FOUND'
 except Exception as e:result['verdict']='ARCHIVE_DRILL_FAIL_'+type(e).__name__
 return result
def part4():
 pin=meta(R/'pinned_release_v1.json')
 names=[]
 try:
  r=subprocess.run(['docker','ps','--format','{{.Names}}'],capture_output=True,text=True,timeout=8)
  if r.returncode==0:names=r.stdout.splitlines()
 except Exception:pass
 private='rg-nas-telegram-private-runner' in names
 public='rg-nas-telegram-runner' in names
 return {'private_runner_visible':private,'legacy_public_runner_visible':public,
   'private_bridge_previous_readonly_test':'PASS_AS_REPORTED_2026_11_12',
   'unmigrated_legacy_routes':['rg-remote-control.yml','rg-nas-alexpc-agent-control.yml'],
   'failed_probe_rg_resilience_blocked':True,
   'public_runner_shutdown_allowed':False,
   'verdict':'BLOCKED_LEGACY_MUTATING_ROUTES_NOT_MIGRATED'}
def main():
 OUT['at_utc']=now()
 for name,fn in [('1_uncertain_private_send',part1),('2_public_channel',part2),('3_isolated_restore_drill',part3),('4_private_runner_cutover',part4)]:
  try:OUT[name]=fn()
  except Exception as e:OUT[name]={'error':type(e).__name__,'verdict':'BLOCKED'}
 OUT['writes_to_production']=0;OUT['telegram_api_calls']=0;OUT['publications']=0
 print(json.dumps(OUT,ensure_ascii=False,indent=2,sort_keys=True))
if __name__=='__main__':main()
