#!/usr/bin/env python3
"""NEWS RG final private automation acceptance, strictly read-only.

Does not call Telegram, poll updates, run scheduler, publish, or modify files.
Separates installed schedule from *observed* autonomous execution evidence.
"""
import os,sys,json,pathlib,time,datetime,hashlib
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
TAG='# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1'
SIDECAR='# NEWS_RG_ISOLATED_SCHEDULE_V2'
ANCHOR='e793f4cd55c5246022bf86e8'
def load(p,limit=100000):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>limit:
  raise RuntimeError('UNSAFE_OR_MISSING_'+p.name)
 return json.loads(p.read_text('utf-8'))
def textfile(p,limit=1000000):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>limit:
  raise RuntimeError('UNSAFE_OR_MISSING_'+p.name)
 return p.read_text('utf-8')
def stamp(p):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>80:
  return None
 try:return float(p.read_text('utf-8').strip())
 except (OSError,ValueError):return None
def latest_receipts():
 receipts=O/'news_rg_private_multipart_receipts_v1'
 decisions=O/'news_rg_editorial_decisions_v1'
 summaries=[]
 if not receipts.is_dir() or receipts.is_symlink():raise RuntimeError('RECEIPTS_DIR_MISSING')
 for p in list(receipts.glob('*.json'))[:10000]:
  r=load(p)
  item={'draft_id':p.stem,'delivery_status':r.get('status'),
        'confirmed_at':r.get('confirmed_at') if isinstance(r.get('confirmed_at'),int) else None}
  if r.get('status')=='PRIVATE_SENT_CONFIRMED':
   item['message_id']=r.get('message_id')
   d=decisions/p.name
   if d.exists():
    o=load(d)
    item['decision_status']=o.get('decision') if (o.get('draft_id')==p.stem
          and o.get('telegram_message_id')==r.get('message_id') and
          o.get('public_publication')=='OFF') else 'INVALID_DECISION'
   else:item['decision_status']='AWAITING_EDITOR'
  summaries.append(item)
 return sorted(summaries,key=lambda x:x.get('confirmed_at') or 0,reverse=True)
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 tick=textfile(B/'rg_news_dsm_tick.sh')
 worker=textfile(O/'rg_news2_p31_guarded_callback_once.py')
 moderator=textfile(B/'rg_moderation.py')
 scrip=textfile(O/'news_rg_private_dispatch_schedule_v1.py')
 dispatch=textfile(O/'news_rg_durable_private_dispatch_v1.py')
 installed=(tick.count(TAG)==1 and tick.count(SIDECAR)==1
      and 'rg_news_guard_rc=$?' in tick
      and 'news_rg_private_dispatch_schedule_v1.py' in tick)
 route=('# NEWS_RG_NE1_OWNER_ROUTE_V1' in worker and
       '# NEWS_RG_EDITORIAL_HOOK_V1' in moderator)
 single_worker=('getUpdates' not in scrip and 'getUpdates' not in dispatch)
 public_guard=('sendMessage' not in scrip and 'sendPhoto' not in scrip
      and 'publish' not in scrip.lower() and
      'sendPhoto' not in dispatch)
 runs=stamp(O/'news_rg_private_dispatch_last_launch')
 last_stage=stamp(O/'news_rg_last_launch_utc')
 receipts=latest_receipts()
 outstanding=[r for r in receipts if r.get('delivery_status')=='PRIVATE_SENT_CONFIRMED'
    and r.get('decision_status')=='AWAITING_EDITOR']
 uncertain=[r for r in receipts if r.get('delivery_status') in
    ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY','HTTP_REJECTED_NO_RETRY')]
 new=[r for r in receipts if r.get('draft_id')!=ANCHOR
    and r.get('delivery_status')=='PRIVATE_SENT_CONFIRMED']
 auto_receipts=[r for r in new if runs is not None and
    r.get('confirmed_at') is not None and
    r['confirmed_at']>=runs-10]
 last_state=O/'news_rg_private_dispatch_status_v1.json'
 try:status=load(last_state,3000) if last_state.exists() else None
 except (ValueError,OSError,RuntimeError):status={'status':'UNREADABLE'}
 log=O/'news_rg_private_dispatch_autorun.log'
 log_present=bool(log.is_file() and not log.is_symlink() and log.stat().st_size>0)
 now=time.time()
 if not installed or not route or not single_worker or not public_guard:
  verdict='AUTOMATION_CONFIGURATION_NEEDS_REPAIR'
 elif uncertain:
  verdict='SAFE_PAUSE_UNCERTAIN_DELIVERY'
 elif runs is None:
  verdict='AWAITING_FIRST_SCHEDULED_DISPATCH_LAUNCH'
 elif auto_receipts:
  verdict='SCHEDULE_DISPATCH_PATH_DELIVERY_CONFIRMED'
 elif status and status.get('status')=='NO_ELIGIBLE_DRAFT':
  verdict='SCHEDULE_LAUNCHED_NO_NEW_ELIGIBLE_DRAFT'
 elif status and status.get('status')=='PAUSED':
  verdict='SCHEDULE_LAUNCHED_PRIVATE_DISPATCH_PAUSED'
 else:
  verdict='SCHEDULE_LAUNCHED_DELIVERY_NOT_YET_PROVEN'
 result={'schema':'NEWS_RG_FINAL_PRIVATE_ACCEPTANCE_V1','status':verdict,
   'read_only':True,'telegram_calls':0,'getUpdates_calls':0,'publications':0,
   'second_pollers_started':0,'dsm_task_script_installed':installed,
   'existing_editorial_route_installed':route,
   'private_worker_has_no_poller':single_worker,
   'public_send_disabled_in_schedule':public_guard,
   'scheduled_private_launcher_seen':runs is not None,
   'private_launch_age_minutes':round((now-runs)/60,1) if runs else None,
   'isolated_ai_launcher_seen':last_stage is not None,
   'isolated_ai_launch_age_minutes':round((now-last_stage)/60,1) if last_stage else None,
   'private_autorun_log_present':log_present,
   'last_private_dispatch_state':status.get('status') if isinstance(status,dict) else None,
   'confirmed_private_cards':len([r for r in receipts if r.get('delivery_status')=='PRIVATE_SENT_CONFIRMED']),
   'outstanding_editorial_cards':len(outstanding),
   'uncertain_receipts':len(uncertain),
   'latest_confirmed_card':({'message_id':newest.get('message_id'),
     'editorial_decision':newest.get('decision_status'),
     'confirmed_at_utc':datetime.datetime.fromtimestamp(newest['confirmed_at'],datetime.timezone.utc).isoformat() if newest.get('confirmed_at') else None}
     if (newest:=next((r for r in receipts if r.get('delivery_status')=='PRIVATE_SENT_CONFIRMED'),None)) else None),
   'new_confirmed_from_schedule_path':len(auto_receipts),
   'public_publication_gate':'OFF',
   'verification_limit':'Launcher marker alone cannot prove DSM task triggered; requires independent task evidence.'}
 print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
def selftest():
 assert TAG.startswith('# NEWS_RG')
 assert 'getUpdates' not in 'print(1)'
 assert len(ANCHOR)==24
 print('NEWS_RG_FINAL_PRIVATE_ACCEPTANCE_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['check']:main()
  else:raise RuntimeError('MODE_EXPECTED_SELFTEST_OR_CHECK')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:110],'publications':0,
                    'getUpdates_calls':0},ensure_ascii=False))
  sys.exit(2)
