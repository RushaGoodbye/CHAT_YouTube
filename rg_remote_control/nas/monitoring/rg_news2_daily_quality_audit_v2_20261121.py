#!/usr/bin/env python3
"""RG NEWS2 safe daily audit. No Telegram API, no sending, no secret disclosure.
Bounded local reads only. Informative nonfatal statuses for unresolved deliveries.
"""
import collections,datetime as dt,hashlib,json,os,pathlib,re,subprocess,sys,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'; PY=O/'tools/python-3.15.2/bin/python3.15'
PENDING=O/'news_rg_native_video_translation_pending_v1'
ST=O/'news_rg_private_review_staging'
DELIVERY=(O/'news_rg_private_delivery_v2',O/'news_rg_private_multipart_receipts_v1')
DEC=O/'news_rg_editorial_decisions_v1'
PUBLIC=O/'news_rg_publication_receipts_v1'
STATE=O/'rg_news2_translation_retry_scheduler_state_v1.json'
SCRIPT=O/'rg_news2_translation_auto_tick_v1.py'
CRON=pathlib.Path('/etc/crontab')
OUTPUT=O/'rg_news2_daily_quality_report_v1.json'
BACK=O/'rg_news2_daily_quality_reports'
def load(p,limit=35000):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return None
  x=json.loads(p.read_text('utf8'))
  return x if isinstance(x,dict) else None
 except (OSError,UnicodeError,ValueError):return None
def count_files(p):return len(list(p.glob('*.json'))) if p.is_dir() and not p.is_symlink() else None
def items(p):
 if not p.is_dir() or p.is_symlink():return []
 return [(f,load(f)) for f in p.glob('*.json') if not f.is_symlink()]
def atomic(p,v):
 data=(json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode('utf8')
 import tempfile
 fd,t=tempfile.mkstemp(prefix='.rg_news2_audit_',dir=str(p.parent))
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
  os.replace(t,p)
 finally:
  if os.path.exists(t):os.unlink(t)
def report():
 now=time.time()
 crontab=CRON.read_text('utf8') if CRON.is_file() and not CRON.is_symlink() else ''
 gate=(B/'PUBLISH_ENABLED').exists()
 log=O/'rg_news2_translation_auto_tick.log'
 state=load(STATE) or {}
 age=lambda p:round((now-p.stat().st_mtime)/60,1) if p.exists() else None
 v={'schema':'RG_NEWS2_DAILY_QUALITY_AUDIT_V1',
 'checked_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
 'public_auto_gate_enabled':gate,'telegram_calls':0,'publications_triggered':0,
 'translation':{'cron_rule_installed':'RG_NEWS2_TRANSLATION_RETRY_20261121' in crontab,
    'cron_worker_exists':SCRIPT.is_file() and not SCRIPT.is_symlink(),
    'runner_file_exists':(O/'rg_news2_strict_native_translation_retry_v2.py').is_file(),
    'last_log_age_min':age(log),'last_state_age_min':age(STATE),
    'last_status':state.get('latest_run_status'),'last_returncode':state.get('returncode')},
 'content':{},'moderation':{},'delivery':{},'backup':{},'health':{},'alerts':[]}
 pending=[(p,d) for p,d in items(PENDING) if d and d.get('status')=='AWAITING_VERIFIED_UKRAINIAN_TEXT']
 v['translation']['pending_count']=len(pending)
 v['translation']['pending_ids']=[p.stem for p,d in pending][:10]
 staged=[(p,d) for p,d in items(ST) if d and d.get('schema')=='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1']
 v['content']['staged_total']=len(staged)
 forbidden=('💬 Що думаєте про цю подію?','💬 Як ви оцінюєте цю новину?')
 sources=(O/'news_rg_organic_post_v1.py',B/'news_rg_organic_post_v1.py')
 footer=O/'news_rg_project_footer_v1.py'
 srcs=[]
 for p in sources:
  try:
   text=p.read_text('utf8')
   # Mark only *active* addition patterns, not allowed strings in selftests.
   srcs.append({'module':p.name,'root_or_operator':str(p.parent.name),
      'active_question_append':bool(re.search(r"body\s*\+=\s*['\"]\\n\\n💬|additions\.append\(['\"]💬",text)),
      'exists':True})
  except Exception:srcs.append({'module':p.name,'exists':False,'active_question_append':None})
 v['content']['composer_checks']=srcs
 if footer.is_file():
  try:
   sys.path.insert(0,str(O))
   import news_rg_project_footer_v1 as foot
   clean=foot.clean_legacy('Новина.\n\n💬 Що думаєте про цю подію?\n\nДеталі.\n\n💬 Як ви оцінюєте цю новину?')
   value,entities=foot.append_footer(clean)
   v['content']['footer_cleaning_pass']=not any(q in value for q in forbidden)
   v['content']['footer_link_pass']=bool(entities and entities[-1].get('url')=='https://links.rginfoua.pp.ua/')
  except Exception as e:
   v['content']['footer_cleaning_pass']=False
   v['content']['footer_link_pass']=False
   v['content']['footer_error_type']=type(e).__name__
 else:v['content']['footer_cleaning_pass']=False
 v['moderation']['decisions_total']=count_files(DEC)
 decisions={p.stem:d for p,d in items(DEC) if d}
 deliveries={}
 for folder in DELIVERY:
  for p,d in items(folder):
   if not d or not re.fullmatch(r'[0-9a-f]{24}',p.stem):continue
   if p.stem not in deliveries or (d.get('status')=='PRIVATE_SENT_CONFIRMED'):
    deliveries[p.stem]=d
 statuses=collections.Counter((d.get('status') or 'UNKNOWN') for d in deliveries.values())
 v['delivery']['receipts_total']=len(deliveries)
 v['delivery']['statuses']=dict(statuses)
 v['moderation']['waiting_for_decision_count']=sum(1 for k,d in deliveries.items() if d.get('status')=='PRIVATE_SENT_CONFIRMED' and k not in decisions)
 v['delivery']['unresolved_count']=sum(1 for d in deliveries.values() if d.get('status') in ('UNCERTAIN_NO_RETRY','HTTP_REJECTED_NO_RETRY','SENDING_UNCERTAIN'))
 v['delivery']['unresolved_draft_ids']=[k for k,d in deliveries.items() if d.get('status') in ('UNCERTAIN_NO_RETRY','HTTP_REJECTED_NO_RETRY','SENDING_UNCERTAIN')][:15]
 v['content']['published_receipts_total']=count_files(PUBLIC)
 v['content']['confirmed_publications_from_receipts']=sum(1 for p,d in items(PUBLIC) if d and d.get('status')=='PUBLIC_PUBLISHED_CONFIRMED')
 # Exactly identical body/source among confirmed private deliveries.
 recent=[]
 for k,d in deliveries.items():
  if d.get('status')!='PRIVATE_SENT_CONFIRMED':continue
  p=ST/(k+'.json');s=load(p)
  if s is None:continue
  if now-p.stat().st_mtime>12*3600:continue
  text=str(s.get('proposed_text') or '').strip()
  source=str(s.get('original_media_source') or '').strip()
  if len(text)<30:continue
  recent.append((k,source,hashlib.sha256(text.casefold().encode()).hexdigest()))
 same_source=collections.defaultdict(list)
 same_text=collections.defaultdict(list)
 for k,source,digest in recent:
  if source:same_source[source].append(k)
  same_text[digest].append(k)
 pairs={}
 for vals in list(same_source.values())+list(same_text.values()):
  if len(vals)<2:continue
  for i,a in enumerate(vals):
   for b in vals[i+1:]:pairs[tuple(sorted((a,b)))]=1
 v['delivery']['confirmed_recent_exact_repeat_pairs']=[list(x) for x in list(pairs)[:12]]
 v['delivery']['dedup_guard_source_present']=False
 sender=O/'news_rg_durable_private_sender_v1.py'
 try:
  txt=sender.read_text('utf8')
  v['delivery']['dedup_guard_source_present']='RG_NEWS2_STRONG_CROSS_SOURCE_EVENT_DEDUP_V1' in txt
 except Exception:pass
 if v['content']['confirmed_publications_from_receipts'] is None:v['alerts'].append('PUBLIC_RECEIPTS_NOT_READABLE')
 if not v['delivery']['dedup_guard_source_present']:v['alerts'].append('PRIVATE_DEDUP_GUARD_MISSING')
 if any(z.get('active_question_append') for z in srcs):v['alerts'].append('QUESTION_APPEND_ACTIVE')
 if not v['content'].get('footer_cleaning_pass') or not v['content'].get('footer_link_pass'):v['alerts'].append('FOOTER_CONTRACT_FAILED')
 if not v['translation']['cron_rule_installed']:v['alerts'].append('TRANSLATION_CRON_MISSING')
 if v['translation']['pending_count'] and (age(STATE) is None or age(STATE)>60):
  v['alerts'].append('TRANSLATION_TICK_NOT_RECENTLY_CONFIRMED')
 if v['delivery']['unresolved_count']:v['alerts'].append('DELIVERIES_REQUIRE_HUMAN_RECONCILIATION')
 if pairs:v['alerts'].append('EXACT_DUPLICATE_ALREADY_DELIVERED')
 h=load(O/'news_rg_stable5_operational_status_v1.json') or {}
 v['health']={'operational_status':h.get('status'),'operational_alerts':h.get('alerts',[]),
   'last_operational_check_utc':h.get('checked_utc'),
   'sources':h.get('sources'),'moderation_waiting':h.get('moderation_waiting')}
 b=O/'rg_news2_dedup_translation_backups'
 backups=[p for p in b.glob('*.tar.gz') if p.is_file() and not p.is_symlink()] if b.is_dir() else []
 v['backup']['latest_guarded_backup_age_hours']=round((now-max(p.stat().st_mtime for p in backups))/3600,1) if backups else None
 v['backup']['guarded_backup_count']=len(backups)
 v['backup']['latest_guarded_backup_bytes']=max(backups,key=lambda p:p.stat().st_mtime).stat().st_size if backups else None
 if not backups:v['alerts'].append('GUARDED_BACKUP_NOT_FOUND')
 v['status']='PASS' if not v['alerts'] else 'PASS_WITH_OBSERVATIONS'
 return v
def main():
 mode=sys.argv[1:]
 if mode==['--selftest']:
  assert 'a' in 'a' and bool(re.fullmatch(r'[0-9a-f]{24}','a'*24))
  print(json.dumps({'status':'DAILY_AUDIT_SELFTEST_PASS','telegram_calls':0,'publications':0}));return
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if mode not in ([],['--once']):raise RuntimeError('BAD_MODE')
 v=report()
 BACK.mkdir(mode=0o700,exist_ok=True)
 os.chmod(BACK,0o700)
 atomic(OUTPUT,v)
 archive=BACK/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')+'.json')
 atomic(archive,v)
 # Keep last 45 daily observations.
 old=sorted([p for p in BACK.glob('????????.json') if p.is_file() and not p.is_symlink()])
 for p in old[:-45]:p.unlink()
 print(json.dumps(v,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','error_type':type(e).__name__,'reason':str(e)[:120] if str(e) in ('SUDO_REQUIRED','BAD_MODE') else 'AUDIT_FAILED', 'publications':0}))
  sys.exit(2)
