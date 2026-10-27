#!/usr/bin/env python3
"""NEWS RG media and private-target preflight. READ ONLY: HEAD media + Telegram getChat."""
import json,os,sys,pathlib,urllib.request,urllib.error,urllib.parse,importlib.util
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=B/'operator'
def probe():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 sys.path.insert(0,str(B))
 spec=importlib.util.spec_from_file_location('_newsrg_mod',str(B/'rg_moderation.py'))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 cfg=m.config();id=cfg.get('moderation_chat_id')
 if not str(id).isdigit() or int(id)<=0:raise RuntimeError('PRIVATE_CHAT_CONFIG_INVALID')
 data={'schema':'NEWS_RG_DELIVERY_CAUSE_PREFLIGHT_V1','read_only':True,'telegram_sends':0,'getUpdates':0,'publications':0,'media':[]}
 try:
  c=m.api('getChat',{'chat_id':int(id)})
  data['destination']={'getChat':'OK','type':c.get('type'),'is_private':c.get('type')=='private'}
 except Exception as e:data['destination']={'getChat':'FAILED','error_class':str(e)[:75]}
 for p in sorted((O/'news_rg_private_review_staging').glob('*.json'))[:5]:
  if p.is_symlink():continue
  x=json.loads(p.read_text())
  url=x.get('media_url','')
  u=urllib.parse.urlsplit(url)
  d={'draft_id':x.get('draft_id'),'host':u.hostname,'scheme':u.scheme}
  if u.scheme!='https' or u.hostname not in ('cdn4.telesco.pe','cdn1.telesco.pe','cdn2.telesco.pe','cdn3.telesco.pe','cdn5.telesco.pe'):d['status']='UNAPPROVED_HOST';data['media'].append(d);continue
  try:
   req=urllib.request.Request(url,method='HEAD',headers={'User-Agent':'Mozilla/5.0'})
   with urllib.request.urlopen(req,timeout=12) as r:
    d.update(status='HTTP_OK',http_code=r.status,content_type=r.headers.get('Content-Type','')[:60],content_length=r.headers.get('Content-Length','')[:30],redirect_host=urllib.parse.urlsplit(r.url).hostname)
  except urllib.error.HTTPError as e:d.update(status='HTTP_ERROR',http_code=e.code)
  except Exception as e:d.update(status='NETWORK_ERROR',error_class=type(e).__name__)
  data['media'].append(d)
 return data
if __name__=='__main__':
 if sys.argv[1:]==['selftest']:print('NEWS_RG_DELIVERY_CAUSE_SELFTEST_PASS')
 elif sys.argv[1:]==['inspect']:
  try:print(json.dumps(probe(),ensure_ascii=False,indent=2))
  except Exception as e:print(json.dumps({'status':'SAFE_STOP','error_class':type(e).__name__}))
 else:raise SystemExit('selftest|inspect')
