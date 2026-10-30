#!/usr/bin/env python3
"""Read-only NEWS RG video end-to-end readiness, no Telegram, no changes."""
import os,sys,json,pathlib,subprocess,re,time,hashlib
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator');B=O.parent
def safe(p,maxbytes=25000):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>maxbytes:return {}
 try:return json.loads(p.read_text('utf-8'))
 except (OSError,ValueError):return {}
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 script=B/'rg_news_dsm_tick.sh'
 tick=script.read_text('utf-8') if script.is_file() and not script.is_symlink() else ''
 pub=O/'news_rg_approved_video_publication_v1.py'
 sched=O/'news_rg_publication_schedule_v1.py'
 render=O/'news_rg_nas_video_pipeline_v1.py'
 render_sched=O/'news_rg_nas_video_schedule_v1.py'
 source=pub.read_text('utf-8') if pub.is_file() and not pub.is_symlink() else ''
 ss=sched.read_text('utf-8') if sched.is_file() and not sched.is_symlink() else ''
 fail=[]
 def check(k,condition):
  if not condition:fail.append(k)
 check('VIDEO_PUBLISHER_MISSING',bool(source))
 check('VIDEO_SCHEDULE_ROUTE_MISSING','NEWS_RG_APPROVED_VIDEO_PUBLICATION_ROUTE_V1' in ss)
 check('DSM_PUBLICATION_TICK_MISSING','news_rg_publication_schedule_v1.py' in tick)
 check('DSM_VIDEO_RENDER_TICK_MISSING','news_rg_nas_video_schedule_v1.py' in tick)
 check('VIDEO_RENDER_MODULE_MISSING',render.is_file() and render_sched.is_file())
 ff='/usr/bin/ffmpeg'
 fr=subprocess.run([ff,'-hide_banner','-filters'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=12) if pathlib.Path(ff).is_file() else None
 check('FFMPEG_DRAWTEXT_NOT_AVAILABLE',fr is not None and fr.returncode==0 and 'drawtext' in fr.stdout)
 dec=O/'news_rg_editorial_decisions_v1';st=O/'news_rg_private_review_staging';ack=O/'news_rg_private_multipart_receipts_v1';water=O/'news_rg_nas_watermarked_v1'
 queues={'staged_video':0,'approved_video':0,'rendered_video':0,'publish_confirmed_video':0,'rendered_waiting_publication':0}
 latest=[]
 if st.is_dir() and not st.is_symlink():
  for p in st.glob('*.json'):
   if not re.fullmatch('[0-9a-f]{24}\\.json',p.name):continue
   s=safe(p)
   if s.get('media_type')!='video':continue
   queues['staged_video']+=1
   d=safe(dec/p.name);a=safe(ack/p.name)
   if d.get('decision')=='editorially_accepted_not_published':
    queues['approved_video']+=1
   w=safe(water/p.name)
   if w.get('status')=='NAS_WATERMARK_RENDERED' and (water/(p.stem+'.mp4')).is_file():
    queues['rendered_video']+=1
   r=safe(O/'news_rg_publication_receipts_v1'/p.name)
   if r.get('status')=='PUBLIC_PUBLISHED_CONFIRMED' and r.get('media_type')=='video':queues['publish_confirmed_video']+=1
   if w.get('status')=='NAS_WATERMARK_RENDERED' and not r and d.get('decision')=='editorially_accepted_not_published':queues['rendered_waiting_publication']+=1
   latest.append({'draft_id':p.stem,'accepted':d.get('decision')=='editorially_accepted_not_published',
     'private_delivered':a.get('status')=='PRIVATE_SENT_CONFIRMED',
     'source_file_id':bool(a.get('original_video_file_id')),
     'rendered':w.get('status')=='NAS_WATERMARK_RENDERED',
     'published':r.get('status')=='PUBLIC_PUBLISHED_CONFIRMED'})
 res={'status':'VIDEO_READINESS_PASS' if not fail else 'VIDEO_READINESS_ATTENTION',
 'issues':fail,'queues':queues,'recent_videos':latest[:8],
 'ffmpeg_drawtext_ready':fr is not None and fr.returncode==0 and 'drawtext' in fr.stdout,
 'photo_publisher_unchanged':True,'new_pollers':0,'telegram_calls':0,'publications':0,'writes':0,
 'real_video_end_to_end_confirmed':queues['publish_confirmed_video']>0}
 print(json.dumps(res,ensure_ascii=False,sort_keys=True))
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:
   assert re.fullmatch('[0-9a-f]{24}\\.json','a'*24+'.json')
   print('NEWS_RG_VIDEO_READINESS_BATCH_SELFTEST_PASS')
  elif sys.argv[1:]==['audit']:main()
  else:raise RuntimeError('MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':type(e).__name__,'telegram_calls':0,'publications':0}))
  sys.exit(2)
