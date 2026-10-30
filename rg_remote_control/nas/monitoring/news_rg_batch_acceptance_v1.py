#!/usr/bin/env python3
"""NEWS RG: one-batch read-only acceptance audit for NAS.
No Telegram requests, publication, polling, scheduler changes or writes.
"""
import os,sys,json,pathlib,time,subprocess,re
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
KEY='f8ad241cbc38ffca55dc7f6f'
def safe(p,limit=24000):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>limit:return None
 try:return json.loads(p.read_text('utf-8'))
 except (OSError,ValueError):return None
def call(name):
 p=O/name
 if not p.is_file() or p.is_symlink():return {'status':'MISSING'}
 try:
  q=subprocess.run(['/usr/bin/python3',str(p),'status'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=12)
  return json.loads(q.stdout.strip().splitlines()[-1]) if q.stdout.strip() else {'status':'NO_OUTPUT','rc':q.returncode}
 except Exception as e:return {'status':'ERROR','class':type(e).__name__}
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 now=time.time()
 state=safe(O/'callback_v29_state.json') or {}
 log=O/'callback_v29.log'
 cron=pathlib.Path('/etc/crontab')
 script=B/'rg_news_dsm_tick.sh'
 crontext=cron.read_text('utf8') if cron.is_file() and not cron.is_symlink() else ''
 ticktext=script.read_text('utf8') if script.is_file() and not script.is_symlink() else ''
 decision=safe(O/'news_rg_editorial_decisions_v1'/(KEY+'.json')) or {}
 pubrec=safe(O/'news_rg_publication_receipts_v1'/(KEY+'.json')) or {}
 privrec=safe(O/'news_rg_private_multipart_receipts_v1'/(KEY+'.json')) or {}
 public=call('news_rg_approved_publication_v1.py')
 dispatch=call('news_rg_durable_private_dispatch_v1.py')
 photo_sender=(O/'news_rg_durable_private_sender_v1.py').read_text('utf8')
 cb=(O/'callback_v29.py').read_text('utf8')
 video=O/'news_rg_nas_video_pipeline_v1.py'
 videosched=O/'news_rg_nas_video_schedule_v1.py'
 accepted_video=[]
 video_st=O/'news_rg_private_review_staging'
 video_dec=O/'news_rg_editorial_decisions_v1'
 video_ack=O/'news_rg_private_multipart_receipts_v1'
 if all(p.is_dir() for p in (video_st,video_dec,video_ack)):
  for p in video_dec.glob('*.json'):
   if not re.fullmatch(r'[a-f0-9]{24}\.json',p.name):continue
   d=safe(p) or {};s=safe(video_st/p.name) or {};r=safe(video_ack/p.name) or {}
   if d.get('decision')=='editorially_accepted_not_published' and s.get('media_type')=='video':
    accepted_video.append({'draft_id':p.stem,'video_file_id_present':bool(r.get('original_video_file_id')),
                           'rendered':(O/'news_rg_nas_watermarked_v1'/(p.stem+'.json')).is_file()})
 issues=[]
 def require(ok,label):
  if not ok:issues.append(label)
 require(state.get('halt') is None and state.get('failures')==0,'CALLBACK_UNHEALTHY')
 require('RG_NEWS2_CALLBACK_PROBATION_V29' in crontext,'CALLBACK_CRON_MISSING')
 require('news_rg_continuous_guarded_v1' in cb and state.get('news_rg_continuous_guarded_v1') is True,'CALLBACK_CONTINUOUS_NOT_INSTALLED')
 require(log.is_file() and now-log.stat().st_mtime<240,'CALLBACK_HEARTBEAT_STALE')
 require(decision.get('decision')=='editorially_accepted_not_published','CARD_8073_DECISION_UNVERIFIED')
 require(privrec.get('telegram_photo_file_id') is not None,'CARD_8073_PHOTO_ID_MISSING')
 require(pubrec.get('status')=='PUBLIC_PUBLISHED_CONFIRMED' and pubrec.get('message_id')==7907,'CARD_8073_PUBLICATION_UNVERIFIED')
 require(public.get('status')=='ACTIVE' and public.get('uncertain_needs_review')==0,'PUBLICATION_NOT_HEALTHY')
 require('news_rg_publication_schedule_v1.py' in ticktext,'PUBLICATION_SCHEDULER_MISSING')
 require("'telegram_photo_file_id':photo_id" in photo_sender,'FUTURE_PHOTO_RECEIPT_FIX_MISSING')
 require(video.is_file() and videosched.is_file() and 'news_rg_nas_video_schedule_v1.py' in ticktext,'VIDEO_RENDER_SCHEDULE_MISSING')
 report={'schema':'NEWS_RG_BATCH_ACCEPTANCE_V1','status':'BASELINE_PASS' if not issues else 'ATTENTION_REQUIRED',
  'issues':issues,'telegram_calls':0,'telegram_sends':0,'publications':0,'writes':0,
  'photo_publication_8073':{'confirmed':pubrec.get('status')=='PUBLIC_PUBLISHED_CONFIRMED','message_id':pubrec.get('message_id')},
  'callback':{'halt':state.get('halt'),'failures':state.get('failures'),'attempts':state.get('attempts'),'heartbeat_age_seconds':int(now-log.stat().st_mtime) if log.is_file() else None},
  'dispatch':{'status':dispatch.get('status'),'outstanding':dispatch.get('outstanding')},
  'publisher':{'status':public.get('status'),'confirmed_count':public.get('published_confirmed'),'uncertain_count':public.get('uncertain_needs_review')},
  'video':{'render_schedule_installed':videosched.is_file(),'render_pipeline_installed':video.is_file(),
           'accepted_video_count':len(accepted_video),'accepted_videos':accepted_video[:5],
           'public_video_delivery':'NOT_IMPLEMENTED_IN_CURRENT_PHOTO_PUBLISHER'},
  'dsm_schedule_detected':bool('news_rg_publication_schedule_v1.py' in ticktext)}
 print(json.dumps(report,ensure_ascii=False,sort_keys=True))
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:
   assert KEY and len(KEY)==24
   print('NEWS_RG_BATCH_ACCEPTANCE_SELFTEST_PASS')
  elif sys.argv[1:]==['audit']:main()
  else:raise RuntimeError('MODE_SELFTEST_OR_AUDIT')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100],'telegram_calls':0,'publications':0}))
  sys.exit(2)
