#!/usr/bin/env python3
"""RG NEWS2 stage2 batch: isolated database restore, receipt correlation and safe cutover gates.
READ ONLY production. Never invokes Telegram API, sends messages, edits live files or stops runners.
"""
from pathlib import Path
from datetime import datetime,timezone
import sqlite3, json, os, time, tempfile, hashlib, subprocess
B=Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=B/'operator'
DB=B/'news.sqlite3'
P=O/'news_rg_private_multipart_receipts_v1'
release=O/'news_rg_stability_releases_v1/pinned_release_v1.json'
report={}
def get(p):
 try:
  if p.is_symlink() or not p.is_file():return {}
  data=json.loads(p.read_text())
  return data if isinstance(data,dict) else {}
 except (OSError,ValueError):return {}
def stamp(v):
 try:return datetime.fromtimestamp(float(v),timezone.utc).isoformat()
 except:return 'UNKNOWN'
def case_db():
 r={'state':'NOT_TESTED','production_db_unchanged':True}
 if not DB.is_file() or DB.is_symlink():return {'state':'BLOCKED_DB_MISSING'}
 before=(DB.stat().st_size,DB.stat().st_mtime_ns)
 try:
  with tempfile.TemporaryDirectory(prefix='rg_sqlite_restore_') as folder:
   dst=Path(folder)/'news_restored.sqlite3'
   src=sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True,timeout=8)
   try:
    backup=sqlite3.connect(str(dst))
    try:src.backup(backup,pages=200,sleep=0.02)
    finally:backup.close()
   finally:src.close()
   check=sqlite3.connect('file:'+str(dst)+'?mode=ro',uri=True)
   try:
    integrity=check.execute('PRAGMA integrity_check').fetchone()[0]
    r.update({'state':'PASS_ISOLATED_DATABASE_SNAPSHOT' if integrity=='ok' else 'FAIL_INTEGRITY',
       'integrity_check':integrity,
       'candidate_rows':check.execute('SELECT count(*) FROM candidates').fetchone()[0],
       'event_rows':check.execute('SELECT count(*) FROM events').fetchone()[0],
       'size_bytes':dst.stat().st_size,
       'note':'Validated a fresh consistent SQLite snapshot in an isolated temporary directory. Not a drill of historical backup retrieval.'})
   finally:check.close()
 except Exception as exc:r.update({'state':'FAIL_'+type(exc).__name__})
 after=(DB.stat().st_size,DB.stat().st_mtime_ns)
 # Concurrent ingestion can change size/mtime; flag, not claim the script changed it.
 r['production_database_changed_while_auditing']=before!=after
 return r
def case_receipts():
 r={'state':'BLOCKED_UNCERTAIN_DELIVERY','unresolved':[],'telegram_api_called':False}
 for f in P.glob('*.json'):
  if f.is_symlink():continue
  v=get(f)
  if v.get('status') not in ('UNCERTAIN_NO_RETRY','SENDING_UNCERTAIN','HTTP_REJECTED_NO_RETRY'):continue
  code=v.get('status')
  r['unresolved'].append({'receipt_name_hash':hashlib.sha256(f.name.encode()).hexdigest()[:12],
    'status':code,'error_class':str(v.get('error_class',''))[:40] if code!='HTTP_REJECTED_NO_RETRY' else 'HTTP_REJECTED',
    'has_message_id':isinstance(v.get('message_id'),int),
    'modified_utc':stamp(f.stat().st_mtime)})
 return r
def case_runner():
 r={'state':'BLOCKED_CUTOVER','public_runner_shutdown_allowed':False,
    'unmigrated_routes':['rg-remote-control.yml','rg-nas-alexpc-agent-control.yml'],
    'private_allowlist_verified':['inspect_auto_edit_files_generic'],
    'disabled_or_unverified':['probe_rg_resilience','mutable AutoEdit commands','NAS remote deploy/scheduler tasks']}
 try:
  p=subprocess.run(['docker','ps','--format','{{.Names}}'],capture_output=True,text=True,timeout=10)
  r['docker_visible']=p.returncode==0
  if p.returncode==0:
   names=p.stdout.splitlines()
   r['private_runner_running']='rg-nas-telegram-private-runner' in names
   r['public_runner_running']='rg-nas-telegram-runner' in names
 except Exception:r['docker_visible']=False
 return r
def case_publishing():
 r={'state':'BLOCKED_LIVE_CONFIRMATION','telegram_api_called':False}
 p=O/'news_rg_stability_healthcheck_v1.py'
 py=O/'tools/python-3.15.2/bin/python3.15'
 try:
  q=subprocess.run([str(py),str(p),'check'],capture_output=True,text=True,timeout=30)
  d=json.loads(q.stdout); pub=d.get('public') or {}
  r['ledger_confirmed']=pub.get('confirmed_publications')
  r['ledger_uncertain']=pub.get('uncertain_sends')
  r['ledger_status']=pub.get('status')
 except Exception as e:r['ledger_error']=type(e).__name__
 return r
report['run_at_utc']=stamp(time.time())
for key,fn in [('database_snapshot_restore',case_db),('uncertain_private_send',case_receipts),('legacy_runner_cutover',case_runner),('publications',case_publishing)]:
 try:report[key]=fn()
 except Exception as e:report[key]={'state':'BLOCKED','reason':type(e).__name__}
report['safe_actions']={'telegram_sends':0,'public_posts':0,'runner_stops':0,'production_db_edits':0}
print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
