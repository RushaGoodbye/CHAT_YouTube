#!/usr/bin/env python3
"""NEWS2 fail-closed batch; local backup and callback/readiness verification only.
No Telegram calls, poller launches, restarts, Cloudflare deploy or public posts.
"""
import ast,datetime as dt,hashlib,json,os,pathlib,sys,tarfile,tempfile,time
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=R/'operator'; B=O/'news_rg_stability_releases_v1'
P=O/'news_rg_poll_moderation_v1.py'
SHA='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
NOW=time.time()
S=O/'news_rg_callback_scheduled_state_v1.json'
G=O/'news_rg_stable5_operational_status_v1.json'
H=O/'news_rg_health_control_state_v1.json'
C=O/'rg_news2_p31_guarded_callback_once.py'
Q=B/'rg_poll_private_pilot_receipt.json'
FILES=[P,S,G,H,C,Q,B/'pinned_release_v1.json',
       O/'news_rg_continuous_callback_v1.py',O/'news_rg_callback_scheduled_tick_v1.py',
       O/'news_rg_autonomous_health_v1.py',O/'news_rg_stable5_operational_gate_v1.py',
       R/'rg_news_dsm_tick.sh']
def js(p):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>350000:return {}
 try:
  x=json.loads(p.read_text('utf8'))
  return x if isinstance(x,dict) else {}
 except (OSError,ValueError,UnicodeError):return {}
def snapshot():
 dest=B/'callback_closeout_backups'
 if dest.is_symlink():raise RuntimeError('UNSAFE_BACKUP_DIR')
 dest.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(dest,0o700)
 fd,tmp=tempfile.mkstemp(dir=dest,prefix='.news2_',suffix='.tar.gz')
 os.close(fd);os.chmod(tmp,0o600)
 try:
  with tarfile.open(tmp,'w:gz') as z:
   for p in FILES:
    if p.is_file() and not p.is_symlink() and p.stat().st_size<=500000:
     z.add(p,arcname=str(p.relative_to(R)),recursive=False)
  stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  out=dest/('news2_closeout_'+stamp+'.tar.gz')
  if out.exists() or out.is_symlink():raise RuntimeError('BACKUP_COLLISION')
  os.replace(tmp,out);os.chmod(out,0o600)
  return {'status':'CREATED','file':out.name,'size_bytes':out.stat().st_size}
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def callback():
 a,b,c=js(S),js(G),js(H)
 age=round(NOW-S.stat().st_mtime) if S.is_file() else None
 healthy=(a.get('status')=='PASS' and a.get('second_poller') is False and
  isinstance(a.get('offset_after'),int) and age is not None and 0<=age<240 and
  b.get('status')=='PASS' and not b.get('alerts') and
  c.get('status')=='HEALTHY' and not c.get('observed_alerts'))
 return {'healthy':healthy,'offset_after':a.get('offset_after'),
  'tick_age_seconds':age,'stable5':b.get('status'),'health':c.get('status'),
  'second_poller':a.get('second_poller')}
def codecheck():
 if not C.is_file() or C.is_symlink():return {'status':'MISSING'}
 t=ast.parse(C.read_text('utf8'))
 strings={n.value for n in ast.walk(t) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
 funcs={n.name for n in t.body if isinstance(n,ast.FunctionDef)}
 parts={'getUpdates': 'getUpdates' in strings,'answerCallbackQuery':'answerCallbackQuery' in strings,
        'getoff':'getoff' in funcs,'putoff':'putoff' in funcs}
 return {'source_contract':'PRESENT' if all(parts.values()) else 'INCOMPLETE',
         'source_checks':parts,'real_callback_ack_verified':False}
def handoff():
 seen={};latest=[]
 for d in (R,O):
  if not d.is_dir():continue
  for p in d.iterdir():
   if not p.name.startswith('updates_handoff_guarded_') or p.suffix!='.json':continue
   try:
    if p.is_symlink() or NOW-p.stat().st_mtime>10800:continue
    x=js(p);key=x.get('input_offset')
    if isinstance(key,int):
     seen[key]=seen.get(key,0)+1;latest.append((p.stat().st_mtime,key))
   except OSError:pass
 return {'recent_archives':sum(seen.values()),'maximum_same_offset_archives':max(seen.values(),default=0),
  'latest_archived_offsets':[offset for _,offset in sorted(latest,reverse=True)[:3]],
  'historical_duplicates_do_not_prove_current_replay':True}
def main():
 if not P.is_file() or P.is_symlink() or hashlib.sha256(P.read_bytes()).hexdigest()!=SHA:
  raise RuntimeError('V6_GUARD_SHA_MISMATCH')
 backup=snapshot()
 current=callback()
 receipt=js(Q)
 out={'status':'NEWS2_LOCAL_PASS_CLOUDFLARE_AND_ACK_PENDING' if current['healthy'] else 'NEWS2_CALLBACK_RECHECK_REQUIRED',
  'v6_integrity':'PASS','backup':backup,'callback':current,'callback_source':codecheck(),
  'test_card_1183_sent':receipt.get('status')=='SENT_PRIVATE' and receipt.get('message_id')==1183,
  'test_card_ack_verified':False,'historical_handoffs':handoff(),
  'cloudflare_source_guard':'COMMITTED','cloudflare_live_deployment':'UNVERIFIED',
  'cloudflare_deploy_performed':False,'public_poll_reenabled':False,
  'telegram_calls':0,'getUpdates_calls':0,'publications':0,'new_pollers':0,'restarts':0}
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'NEWS2_FAIL_CLOSED','reason':str(e)[:100] if isinstance(e,RuntimeError) else type(e).__name__,
    'telegram_calls':0,'publications':0,'restarts':0},ensure_ascii=False))
  sys.exit(2)
