#!/usr/bin/env python3
"""NEWS2 callback exact-offset and private QA#1183 receipt audit. Read-only.
Never calls Telegram API, never starts pollers, no state change, no raw updates output.
"""
import datetime,hashlib,json,os,pathlib,re,sys,time
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=R/'operator'
NOW=time.time()
EXPECTED='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
KNOWN_MSG=1183
def safe_obj(p,limit=1000000):
 try:
  if not p.is_file() or p.is_symlink() or p.stat().st_size>limit:return None
  return json.loads(p.read_text('utf8'))
 except (OSError,ValueError,UnicodeError):return None
def present(p):
 try:return p.is_file() and not p.is_symlink()
 except OSError:return False
def collect_updates():
 paths=[]
 for d in [R,O]:
  if d.is_dir():
   for p in d.iterdir():
    if p.is_file() and p.name.startswith('updates_handoff_guarded_') and p.suffix=='.json':
     try:
      if NOW-p.stat().st_mtime<=7200:paths.append(p)
     except OSError:pass
 paths=sorted(paths,key=lambda p:p.stat().st_mtime,reverse=True)[:180]
 rows=[];by_offset={};matching=[];callback_hashes={};sample_by_id={}
 for p in paths:
  obj=safe_obj(p)
  if not isinstance(obj,dict):continue
  off=obj.get('input_offset')
  if isinstance(off,int):by_offset[off]=by_offset.get(off,0)+1
  updates=obj.get('updates')
  if not isinstance(updates,list):continue
  counts={'callbacks':0,'messages':0,'update_ids':0}
  for u in updates[:100]:
   if not isinstance(u,dict):continue
   uid=u.get('update_id')
   if isinstance(uid,int):
    counts['update_ids']+=1
    sample_by_id[uid]=sample_by_id.get(uid,0)+1
   cb=u.get('callback_query')
   if isinstance(cb,dict):
    counts['callbacks']+=1
    action=str(cb.get('data','')).split(':')[1:2]
    message=cb.get('message') or {}
    mid=message.get('message_id') if isinstance(message,dict) else None
    is_test=mid==KNOWN_MSG
    sig=hashlib.sha256(str(cb.get('id','')).encode('utf8')).hexdigest()[:14]
    callback_hashes[sig]=callback_hashes.get(sig,0)+1
    if is_test:
     matching.append({'archive':p.name,'offset':off,'action':action[0] if action else None,
       'message_id':KNOWN_MSG,'callback_id_hash_prefix':sig,'update_id':uid})
   elif 'message' in u:counts['messages']+=1
  rows.append({'offset':off,**counts})
 duplicate=[{'offset':k,'handoff_files':v} for k,v in sorted(by_offset.items(),key=lambda kv:-kv[1])[:10]]
 repeated=[{'callback_hash_prefix':k,'appearances':v} for k,v in callback_hashes.items() if v>1]
 duplicated_updates=sum(1 for v in sample_by_id.values() if v>1)
 return {'recent_archives_checked':len(rows),'offset_frequency':duplicate,
  'repeated_callback_hashes':sorted(repeated,key=lambda x:-x['appearances'])[:10],
  'repeated_update_ids_count':duplicated_updates,
  'test_1183_archive_matches':matching[:10],
  'test_1183_archive_occurrences':len(matching),
  'same_offset_reused':any(n>1 for n in by_offset.values())}
def states():
 names=['news_rg_callback_scheduled_state_v1.json','news_rg_stable5_operational_status_v1.json',
        'news_rg_autonomous_health_v1.json','news_rg_health_control_state_v1.json',
        'rg_poll_private_pilot_receipt.json']
 out=[]
 for name in names:
  for d in [R,O,O/'news_rg_stability_releases_v1']:
   p=d/name
   data=safe_obj(p,300000)
   if not isinstance(data,dict):continue
   row={'file':name,'age_seconds':int(NOW-p.stat().st_mtime)}
   for k in ('status','offset_after','offset_before','updates','second_poller','callback_age_seconds','alerts',
             'observed_alerts','checked_at_utc','message_id','last_guard_status'):
    v=data.get(k)
    if isinstance(v,(str,int,float,bool)) or (k in ('alerts','observed_alerts') and isinstance(v,list)):
     if k=='message_id' and v!=KNOWN_MSG:continue
     row[k]=v
   out.append(row)
 return out
def receipts():
 # Search metadata-oriented callback receipts; do not expose raw content.
 result=[]
 for d in [R,O]:
  if not d.is_dir():continue
  count=0
  for p in d.iterdir():
   if count>400:break
   count+=1
   if not present(p) or p.suffix!='.json':continue
   if not any(x in p.name.lower() for x in ('callback','handoff','poll','moderation','telegram')):continue
   if p.name.startswith('updates_handoff_guarded_'):continue
   if NOW-p.stat().st_mtime>7200:continue
   data=safe_obj(p,300000)
   if not isinstance(data,dict):continue
   # Match exact test message by explicit standard message id fields, not raw text.
   found=any(data.get(k)==KNOWN_MSG for k in
              ('message_id','private_message_id','moderator_message_id','test_message_id'))
   if found:
    result.append({'file':p.name,'age_seconds':round(NOW-p.stat().st_mtime),
                   'status':str(data.get('status',''))[:70]})
 return result[:20]
def main():
 p=O/'news_rg_poll_moderation_v1.py'
 pinned=present(p) and hashlib.sha256(p.read_bytes()).hexdigest()==EXPECTED
 report={'status':'RG_NEWS2_CALLBACK_OFFSET_BATCH_READONLY',
  'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'v6_integrity_pass':pinned,'test_private_message_id':KNOWN_MSG,
  'callback_handoffs':collect_updates(),'callback_status':states(),
  'direct_test_receipts':receipts(),
  'interpretation':'Archive presence is evidence of receipt, not proof of callback acknowledgment.',
  'telegram_calls':0,'getUpdates_calls':0,'publications':0,
  'restarts':0,'files_changed':0}
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as exc:
  print(json.dumps({'status':'RG_NEWS2_CALLBACK_OFFSET_SAFE_STOP',
     'error':type(exc).__name__,'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
