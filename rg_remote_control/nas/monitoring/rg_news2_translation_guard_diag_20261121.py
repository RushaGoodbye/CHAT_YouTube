#!/usr/bin/env python3
"""NEWS2 one-shot diagnosis for protected native-video pending translation.
READ ONLY: makes at most one Gemini draft request for the freshest pending entry,
checks exactly the production editorial guards, never prints text, credentials
or file_id, never modifies queues, no Telegram actions.
"""
import datetime as dt,json,os,pathlib,re,sys,time,urllib.error
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
P=O/'news_rg_native_video_translation_pending_v1'
sys.path.insert(0,str(O))
def output(**d):print(json.dumps(d,ensure_ascii=False,indent=2),flush=True)
def need(c,reason):
 if not c:raise RuntimeError(reason)
def load(f):
 if f.is_symlink() or not f.is_file() or f.stat().st_size>16000:return None
 try:
  v=json.loads(f.read_text('utf8'))
  return v if isinstance(v,dict) else None
 except Exception:return None
def run():
 need(os.geteuid()==0,'SUDO_REQUIRED')
 need(P.is_dir() and not P.is_symlink(),'PENDING_DIR_UNAVAILABLE')
 import news_rg_gemini_35_adapter_v1 as adapter
 import news_rg_manual_link_intake_v1 as intake
 records=[]
 for p in P.glob('*.json'):
  d=load(p)
  if d and d.get('schema')=='RG_NATIVE_VIDEO_PENDING_UKRAINIAN_V1' and d.get('status')=='AWAITING_VERIFIED_UKRAINIAN_TEXT':
   records.append((p,d))
 records.sort(key=lambda pair:pair[0].stat().st_mtime,reverse=True)
 out={'status':'NEWS2_TRANSLATION_DIAGNOSTIC','at':dt.datetime.now(dt.timezone.utc).isoformat(),
   'pending_count':len(records),'attempted':0,'telegram_calls':0,
   'publications':0,'queue_modifications':0,'new_pollers':0,'public_gate':'OFF'}
 out['overview']=[{
  'pending_id':p.stem,
  'age_minutes':round((time.time()-p.stat().st_mtime)/60,1),
  'source_chars':len(str(d.get('original_text') or '')),
  'video_bytes':d.get('original_video_file_size'),
  'russian_only_chars':bool(re.search(r'[ыъэёЫЪЭЁ]',str(d.get('original_text') or ''))),
  'ukrainian_chars':bool(re.search(r'[іїєґІЇЄҐ]',str(d.get('original_text') or ''))),
  'review_gate':d.get('editorial_status')
 } for p,d in records][:10]
 if not records:
  out['status']='NOTHING_PENDING';output(**out);return
 p,d=records[0]
 orig=d.get('original_text')
 need(type(orig)==str and 60<=len(orig)<=3500,'SOURCE_TEXT_NOT_ELIGIBLE')
 need(d.get('public_publication')=='OFF' and d.get('telegram_delivery')=='NOT_SENT','PENDING_PUBLICATION_GATE_CHANGED')
 out['target_pending_id']=p.stem
 key=adapter.credential()
 if not key:
  out['status']='MODEL_KEY_NOT_AVAILABLE';output(**out);return
 out['attempted']=1
 try:
  obj=adapter.rewrite(orig,key)
  draft=obj['draft']
  out['provider']='GEMINI_DRAFT_RECEIVED'
  out['draft_chars']=len(draft)
  out['adapter_verify']=adapter.verify(orig,draft) or 'PASS'
  out['intake_ukrainian_draft_ok']=bool(intake.ukrainian_draft_ok(orig,draft))
  out['result']='READY_FOR_STAGING' if out['intake_ukrainian_draft_ok'] else 'PRODUCTION_INTAKE_GUARD_REJECTED'
  out['status']='DIAG_COMPLETE'
 except urllib.error.HTTPError as ex:
  out['status']='GEMINI_HTTP_ERROR';out['http_code']=ex.code
 except Exception as ex:
  reason=str(ex)
  out['status']='GEMINI_OR_EDITORIAL_REJECTED'
  out['error_class']=type(ex).__name__
  # Only emit our known guard codes. Provider raw messages could contain private text.
  out['guard_code']=reason[:100] if reason.startswith(('EDITORIAL_GUARD:','NO_CANDIDATE')) else 'PROVIDER_OR_UNKNOWN_ERROR'
 output(**out)
if __name__=='__main__':
 try:run()
 except Exception as exc:
  output(status='SAFE_STOP',error_type=type(exc).__name__,reason=str(exc)[:100]
      if str(exc) in ('SUDO_REQUIRED','PENDING_DIR_UNAVAILABLE','SOURCE_TEXT_NOT_ELIGIBLE','PENDING_PUBLICATION_GATE_CHANGED') else 'SAFE_STOP',
      telegram_calls=0,publications=0,queue_modifications=0)
  sys.exit(2)
