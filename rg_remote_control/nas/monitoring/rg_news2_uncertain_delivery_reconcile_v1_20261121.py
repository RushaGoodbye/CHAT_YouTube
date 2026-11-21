#!/usr/bin/env python3
"""NEWS2 forensic reconciliation: read-only exact evidence for uncertain private send receipts.
Never sends/retries Telegram, never edits receipts, no poller, no secret output.
"""
import collections,datetime as dt,json,os,pathlib,re,sys,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=B/'operator'
DIRECTORIES=(O/'news_rg_private_delivery_v2',O/'news_rg_private_multipart_receipts_v1')
DEC=O/'news_rg_editorial_decisions_v1'
ST=O/'news_rg_private_review_staging'
PUB=O/'news_rg_publication_receipts_v1'
LOGS=(O/'news_rg_manual_link_dispatch_v1.log',O/'rg_native_dispatch_20261116.log',O/'news_rg_private_dispatch_autorun.log',O/'news_rg_continuous_callback.log')
VALID=re.compile(r'^[0-9a-f]{24}$')
def read(p,limit=50000):
 try:
  if not p.is_file() or p.is_symlink() or p.stat().st_size>limit:return None
  z=json.loads(p.read_text('utf8'))
  return z if isinstance(z,dict) else None
 except Exception:return None
def proof_in_logs(key):
 observations=[]
 for p in LOGS:
  if p.is_symlink() or not p.is_file():continue
  try:
   # Read all dispatched records for exact draft_id. No unstructured log output.
   matches=[]
   with p.open('r',encoding='utf8',errors='replace') as f:
    for line in f:
     if key not in line:continue
     if len(line)>15000:continue
     matches.append(line)
     if len(matches)>20:break
   for line in matches:
    for raw in (line,):
     try:
      obj=json.loads(raw.strip())
      if not isinstance(obj,dict):continue
      node=obj.get('stdout')
      if isinstance(node,str):
       try:node=json.loads(node.strip())
       except Exception:node=None
      for z in (obj,node):
       if not isinstance(z,dict):continue
       if z.get('draft_id')!=key:continue
       observations.append({'log':p.name,'status':z.get('status'),
            'message_id':z.get('message_id') if type(z.get('message_id'))==int else None})
     except Exception:continue
  except Exception:continue
 return observations[:30]
def one_record(key,receipts):
 rec={'draft_id':key,'sources':[],'confirmed_message_ids':[]}
 for p,z in receipts:
  rec['sources'].append({'directory':p.parent.name,'status':z.get('status'),
     'message_id':z.get('message_id') if type(z.get('message_id'))==int else None,
     'http_status':z.get('http_status') if type(z.get('http_status'))==int else None,
     'error_class':str(z.get('error_class',''))[:80] or None,
     'last_change_utc':dt.datetime.fromtimestamp(p.stat().st_mtime,dt.timezone.utc).isoformat()})
  if z.get('status')=='PRIVATE_SENT_CONFIRMED' and type(z.get('message_id'))==int and z['message_id']>0:
   rec['confirmed_message_ids'].append(z['message_id'])
 decision=read(DEC/(key+'.json'))
 rec['decision']={'present':bool(decision),
  'decision':decision.get('decision') if decision else None,
  'telegram_message_id':decision.get('telegram_message_id') if decision and type(decision.get('telegram_message_id'))==int else None}
 stage=read(ST/(key+'.json'))
 rec['staging']={'exists':bool(stage),
   'status':stage.get('editorial_status') if stage else None,
   'media_type':stage.get('media_type') if stage else None,
   'telegram_delivery':stage.get('telegram_delivery') if stage else None}
 pub=read(PUB/(key+'.json'))
 rec['public_receipt']={'exists':bool(pub),'status':pub.get('status') if pub else None}
 rec['dispatch_log_proofs']=proof_in_logs(key)
 candidates=set(rec['confirmed_message_ids'])
 candidates|={x['message_id'] for x in rec['dispatch_log_proofs'] if x['status']=='PRIVATE_SENT_CONFIRMED' and type(x['message_id'])==int}
 if decision and decision.get('draft_id')==key and type(decision.get('telegram_message_id'))==int:
  candidates.add(decision['telegram_message_id'])
 if len(candidates)==1:
  rec['evidence']='SINGLE_MESSAGE_ID_CONFIRMED_IN_LOCAL_RECORDS'
  rec['evidence_message_id']=next(iter(candidates))
 elif len(candidates)>1:
  rec['evidence']='CONFLICTING_MESSAGE_IDS_MANUAL_REVIEW'
 else:
  rec['evidence']='NO_LOCAL_SEND_CONFIRMATION'
 if rec['decision']['present'] and len(candidates)==1 and rec['decision']['telegram_message_id'] not in candidates:
  rec['evidence']='DECISION_CONFLICT_MANUAL_REVIEW'
 # HTTP-rejected receipts are definitively refused by API, but do not auto retry.
 if rec['evidence']=='NO_LOCAL_SEND_CONFIRMATION' and all(x['status']=='HTTP_REJECTED_NO_RETRY' for x in rec['sources']):
  rec['evidence']='HTTP_REJECTED_NO_RETRY_NO_DELIVERY_PROOF'
 rec['safe_auto_close']=False
 return rec
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 collected=collections.defaultdict(list)
 for folder in DIRECTORIES:
  if not folder.is_dir() or folder.is_symlink():continue
  for p in folder.glob('*.json'):
   if not VALID.fullmatch(p.stem):continue
   z=read(p)
   if z:collected[p.stem].append((p,z))
 unresolved=[]
 for key,rows in collected.items():
  statuses={z.get('status') for p,z in rows}
  if statuses.intersection(('UNCERTAIN_NO_RETRY','SENDING_UNCERTAIN','HTTP_REJECTED_NO_RETRY')):
   unresolved.append(one_record(key,rows))
 unresolved.sort(key=lambda x:x['draft_id'])
 # Also inspect duplicate receipts for same key, with conflicting status.
 summary={'status':'READONLY_UNCERTAIN_RECONCILIATION','checked_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
  'total_unresolved':len(unresolved),'records':unresolved,
  'auto_closed':0,'telegram_calls':0,'second_pollers':0,'publications':0,
  'recommendation':'Never re-send uncertain items without external Telegram verification.'}
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','error_type':type(e).__name__,'reason':str(e)[:80] if str(e)=='SUDO_REQUIRED' else 'READ_ONLY_DIAG_ERROR','telegram_calls':0,'publications':0}))
  sys.exit(2)
