#!/usr/bin/env python3
"""NEWS2 focused root-only diagnostic for stuck translations and duplicate ship cards.
Read only. No bot API/network, no public sends, no writes.
"""
import pathlib,json,time,hashlib,collections,re,os,datetime
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
PENDING=O/'news_rg_native_video_translation_pending_v1'
ST=O/'news_rg_private_review_staging'
REC=O/'news_rg_publication_receipts_v1'
def read(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>200000:return {}
  x=json.loads(p.read_text('utf8'))
  return x if isinstance(x,dict) else {}
 except Exception:return {}
def digest(x):return hashlib.sha256(str(x).encode()).hexdigest()[:16]
def safe_rec(p,obj):
 text=' '.join(str(obj.get(k) or '') for k in ('original_text','proposed_text','title','caption','text','body','source','original_media_source','source_key'))
 ship=any(z in text.lower() for z in ('корабл','судно','фінськ','ленінград','калінінград'))
 lav=any(z in text.lower() for z in ('лавров','лаврова'))
 keys=['schema','status','editorial_status','telegram_delivery','media_type','review_media','translation_status','translation_attempts','translation_error','retry_at','prepared_at','posted_at','last_attempt_at','message_id','source_id','original_video_file_size','manual_submission','public_publication','draft_id','pending_id','source']
 keep={k:obj.get(k) for k in keys if k in obj and not any(x in k for x in ('token','secret','password'))}
 for k in ('source_key','original_media_source','original_video_file_id','original_video_file_unique_id','text','caption','original_text','proposed_text','raw_caption'):
  if obj.get(k):
   keep[k+'_fingerprint']=digest(obj[k])
   if k in ('original_text','proposed_text','caption','text','raw_caption'):
    keep[k+'_length']=len(str(obj[k]))
 keep.update(filename=p.name,age_minutes=round((time.time()-p.stat().st_mtime)/60,1), topic='LAVROV' if lav else 'SHIP' if ship else 'OTHER')
 return keep
def collect(d,all_items=False):
 out=[]
 if not d.is_dir():return out
 for p in d.glob('*.json'):
  q=read(p)
  if not q:continue
  r=safe_rec(p,q)
  if all_items or r['topic'] in ('SHIP','LAVROV'):out.append(r)
 return sorted(out,key=lambda r:r['age_minutes'])
def excerpt(p,starts,limit=80):
 try:
  lines=p.read_text('utf8').splitlines()
 except Exception:return {'file':p.name,'available':False}
 output=[]
 for i,s in enumerate(lines):
  if any(x in s for x in starts):
   lo=max(0,i-3);hi=min(len(lines),i+12)
   for j in range(lo,hi):
    if len(output)>=limit:break
    line=lines[j]
    if re.search('token|password|secret|api_hash|api_id|authorization',line,re.I):continue
    record={'line':j+1,'code':line[:230]}
    if record not in output:output.append(record)
 return {'file':p.name,'lines':output}
def run():
 out={'status':'NEWS2_TRANSLATION_DUPLICATE_FORENSIC_V2','uid':os.geteuid(),'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'telegram_calls':0,'publications':0,'modifications':0}
 out['translation_pending'] = collect(PENDING,True)[:20]
 all_st=collect(ST)
 out['recent_ship_and_lavrov']=[x for x in all_st if x['age_minutes']<360][-25:]
 out['receipts']=[x for x in collect(REC,True) if x['age_minutes']<360][:30]
 # Exact topic fingerprint comparison: group by source identity, not broad keywords.
 topic=[x for x in all_st if x['topic']=='SHIP' and x['age_minutes']<360]
 g=collections.defaultdict(list)
 for x in topic:
  key=x.get('original_media_source_fingerprint') or x.get('source_key_fingerprint') or x.get('original_text_fingerprint') or x.get('proposed_text_fingerprint')
  if key:g[key].append(x['filename'])
 out['exact_source_fingerprint_duplicates']={k:v for k,v in g.items() if len(v)>1}
 out['modules']=[]
 for n,keys in [
 ('news_rg_manual_link_intake_v1.py',('def preserve_native_video_pending_ukrainian','def stage_native_video_file','NATIVE_VIDEO_SAVED_TRANSLATION_PENDING','TRANSLATION_REQUIRED_BEFORE_MODERATION','prepare_ukrainian_with_status')),
 ('news_rg_manual_retry_v1.py',('def tick(','def retry','already_staged','MANUAL_LINK_ALREADY_QUEUED')),
 ('news_rg_durable_private_dispatch_v1.py',('MAX_OUTSTANDING','eligible','already_sent')),
 ('rg_news2_outbound_queue_v2.py',('event_duplicate','source_id','duplicate','fingerprint')),
 ('news_rg_editorial_rank_v1.py',('def event_duplicate',)),
 ('news_rg_native_video_translation_retry_v1.py',('def ','retry','pending')),
 ]:
  out['modules'].append(excerpt(O/n,keys,65))
 out['candidate_translation_modules']=[p.name for p in O.glob('*.py') if any(w in p.name for w in ('translat','native_video','pending'))][:40]
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
