#!/usr/bin/env python3
"""RG NEWS2 non-mutating forensic diagnostic for manual translation and duplicate ship cards.
Prints only bounded state, safe source snippets and metadata; no API/network calls.
"""
import pathlib,json,datetime as dt,re,os,collections,hashlib,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=B/'operator'
now=time.time()
def load(p):
 try:
  if not p.is_file() or p.is_symlink() or p.stat().st_size>200000:return None
  v=json.loads(p.read_text('utf8'))
  return v if isinstance(v,dict) else None
 except Exception:return None
def cat(s):
 s=str(s or '').lower()
 return ('LAVROV' if any(w in s for w in ('лавров','ла́вров')) else
         'SHIP' if any(w in s for w in ('судно','корабл','фінськ','калінінград','ленінград')) else 'OTHER')
def entry(p,d):
 txt=' '.join(str(d.get(k) or '')[:2000] for k in
  ('original_text','proposed_text','caption','text','body','title','source','original_media_source','source_key','translation_note','error'))
 return {'file':p.name,'age_minutes':round((now-p.stat().st_mtime)/60,1),
 'topic':cat(txt),'status':d.get('status'),'editorial_status':d.get('editorial_status'),
 'telegram_delivery':d.get('telegram_delivery'),'media_type':d.get('media_type'),
 'manual_submission':d.get('manual_submission'), 'review_media':d.get('review_media'),
 'source_key_digest':hashlib.sha256(str(d.get('source_key') or d.get('original_media_source') or '').encode()).hexdigest()[:12],
 'original_video_file_size':d.get('original_video_file_size'),
 'message_id':d.get('message_id'),'draft_id':d.get('draft_id'),
 'has_original_video_file_id':bool(d.get('original_video_file_id')),
 'has_proposed_text':bool(d.get('proposed_text')),'public_publication':d.get('public_publication')}
def scan_dir(p):
 if not p.is_dir() or p.is_symlink():return {}
 arr=[];total=0
 for f in p.iterdir():
  if f.suffix!='.json' or f.is_symlink() or not f.is_file():continue
  total+=1;d=load(f)
  if not d:continue
  e=entry(f,d)
  if e['topic']!='OTHER' or e['age_minutes']<90:arr.append(e)
 return {'path':str(p.relative_to(B)),'total_json':total,
    'topic_matches':[e for e in arr if e['topic']!='OTHER'][-30:],
    'latest':[e for e in sorted(arr,key=lambda x:x['age_minutes'])[:12]]}
def source_hits(p):
 try:
  t=p.read_text('utf8')
  lines=t.splitlines();hits=[]
  patterns=('TRANSLAT','переклад','manual_translation','MAX_OUTSTANDING','ALREADY_QUEUED','NATIVE_VIDEO','original_video_file_id','SHIP','dedup','duplicate','same_source','requeue')
  for i,s in enumerate(lines):
   if any(x.lower() in s.lower() for x in patterns):
    if len(hits)>=24:break
    # omit any lines that may be credentials, secrets or personal data
    if any(x in s.lower() for x in ('token','password','secret','authorization','api_key','api_id','api_hash')):continue
    hits.append({'line':i+1,'snippet':s.strip()[:160]})
  return {'file':p.name,'matches':hits}
 except Exception as exc:return {'file':p.name,'error':type(exc).__name__}
def run():
 out={'status':'RG_NEWS2_QUEUE_DIAG_READONLY','at':dt.datetime.now(dt.timezone.utc).isoformat(),
      'uid':os.geteuid(),'telegram_calls':0,'publications':0}
 out['dirs']=[]
 for n in ('news_rg_private_review_staging','news_rg_publication_receipts_v1','news_rg_manual_retry_queue_v1',
           'news_rg_manual_link_pending_v1','rg_news2_native_video_queue_v1',
           'rg_news2_manual_translation_queue_v1','rg_news2_outbound_queue_v2'):
  p=O/n
  if p.is_dir():out['dirs'].append(scan_dir(p))
 others=[]
 for p in O.iterdir():
  if not p.is_dir() or p.is_symlink():continue
  low=p.name.lower()
  if any(k in low for k in ('translat','retry','forward','native','queue','pending','manual')) and \
    p.name not in {x['path'].split('/')[-1] for x in out['dirs']}:
   try:count=sum(1 for f in p.iterdir() if f.suffix=='.json' and f.is_file())
   except OSError:count=None
   others.append({'folder':p.name,'json_count':count})
 out['other_candidate_dirs']=others[:40]
 out['states']={}
 for n in ('rg_news2_queue_health_last_v1.json','news_rg_callback_scheduled_state_v1.json','news_rg_stable5_operational_status_v1.json'):
  d=load(O/n) or {}
  out['states'][n]={k:v for k,v in d.items() if not any(x in k.lower() for x in ('token','secret','password','key','api','chat'))}
 out['source_matches']=[source_hits(O/n) for n in
  ('news_rg_manual_link_intake_v1.py','rg_news2_p31_guarded_callback_once.py',
    'news_rg_manual_retry_v1.py','rg_news2_outbound_queue_v2.py',
    'news_rg_durable_private_dispatch_v1.py','news_rg_editorial_rank_v1.py')]
 out['logs']={}
 for n in ('news_rg_manual_link_dispatch_v1.log','rg_native_dispatch_20261116.log'):
  p=O/n
  try:
   lines=p.read_text('utf8',errors='replace').splitlines()[-25:]
   statuses=[]
   for line in lines:
    if 'status' not in line:continue
    try:
     d=json.loads(line)
     if 'stdout' in d:
      d=json.loads(d['stdout'])
     statuses.append({k:d.get(k) for k in ('status','draft_id','message_id','reason','publications','buttons') if k in d})
    except Exception:continue
   out['logs'][n]=statuses[-15:]
  except Exception as e:out['logs'][n]=type(e).__name__
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
