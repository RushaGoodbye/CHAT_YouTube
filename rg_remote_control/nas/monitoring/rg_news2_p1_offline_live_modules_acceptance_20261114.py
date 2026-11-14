#!/usr/bin/env python3
"""NEWS2 package1 no-network acceptance on exact live modules (SMB read only).

Tests real implementations of ne1 callbacks and public photo, album, text,
video publishers against isolated temporary ledgers, mocked Telegram.
Never performs any real Telegram request, root work, NAS write or publication.
"""
import sys,types,os,tempfile,time,json,hashlib,importlib.util,pathlib,copy
from pathlib import Path
sys.modules['fcntl']=types.SimpleNamespace(flock=lambda *args:None,LOCK_EX=2,LOCK_NB=4)
if not hasattr(os,'fchmod'):os.fchmod=lambda fd,mode:None
O=Path(r'\\192.168.50.32\docker\RG_TELEGRAM_NEWS_2\operator')
sys.path.insert(0,str(O))
def load(name):
    spec=importlib.util.spec_from_file_location(name,str(O/(name+'.py')))
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
cb=load('news_rg_editorial_callbacks_v1')
p=load('news_rg_approved_publication_v1')
t=load('news_rg_approved_text_publication_v1')
v=load('news_rg_approved_video_publication_v1')
footer=load('news_rg_project_footer_v1')
album=types.ModuleType('rg_video_album_bridge_v2')
album.choose_approved=lambda activation:None
sys.modules['rg_video_album_bridge_v2']=album
now=int(time.time());act={'status':'ACTIVE','schema':'NEWS_RG_PUBLICATION_ACTIVATION_V1',
    'activated_at':now-1000,'chat_id':-1001755891079,'bot_id':9130632602}
mod={'moderators':[12345],'moderation_chat_id':12345}
caption='Сили оборони України повідомили про результати операції на фронті, деталі уточнюються офіційними джерелами.'
checks=[]
with tempfile.TemporaryDirectory(prefix='news2_p1_no_telegram_') as td:
 root=Path(td)
 paths={k:root/k for k in ['st','priv','dec','pub','render']}
 for f in paths.values():f.mkdir()
 for obj in (p,t,cb):
  if hasattr(obj,'STAGED'):obj.STAGED=paths['st']
  if hasattr(obj,'ST'):obj.ST=paths['st']
  if hasattr(obj,'DEC'):obj.DEC=paths['dec']
  if hasattr(obj,'DECISIONS'):obj.DECISIONS=paths['dec']
  if hasattr(obj,'SENT'):obj.SENT=paths['priv']
  if hasattr(obj,'RECEIPTS'):obj.RECEIPTS=paths['priv']
  if hasattr(obj,'PUB'):obj.PUB=paths['pub']
 p.LCK=root/'pub.lock';p.gate=lambda:act;p.module=lambda:{}
 p.credentials=lambda:'OFFLINE_NO_REAL_TOKEN'
 p.verify_channel=lambda cfg,token:{'chat_id':act['chat_id'],'bot_id':act['bot_id']}
 t.ST=paths['st'];t.DEC=paths['dec'];t.SENT=paths['priv'];t.PUB=paths['pub']
 v.OUT=paths['render'];v.base=lambda:p
 calls=[]
 def fake_api(method,payload,token):
  assert token=='OFFLINE_NO_REAL_TOKEN'
  assert int(payload['chat_id'])==act['chat_id']
  calls.append((method,payload))
  if method=='sendMediaGroup':
   media=json.loads(payload['media'])
   assert len(media)==2
   assert media[0]['caption_entities'][1]['type']=='text_link'
   return [{'message_id':501+i,'chat':{'id':act['chat_id']},'photo':[{'file_id':'X'}]} for i in range(2)]
  if method in ('sendPhoto','sendMessage'):
   entities=json.loads(payload.get('caption_entities') or payload.get('entities'))
   assert entities[0]['type']=='bold' and entities[1]['type']=='text_link'
   assert entities[1]['url']=='https://links.rginfoua.pp.ua/'
   return {'message_id':500+len(calls),'chat':{'id':act['chat_id']}}
  raise AssertionError('REAL_NETWORK_UNEXPECTED_'+method)
 p.telegram=fake_api
 def stage(key,kind,album_count=0,video_mode=None):
  s={'schema':'NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1','draft_id':key,
     'public_publication':'OFF','proposed_text':caption,
     'media_type':kind,
     'editorial_status':'HUMAN_FACT_AND_'+('PHOTO' if kind=='photo' else 'TEXT' if kind=='text' else 'VIDEO')+'_REVIEW_REQUIRED'}
  if kind=='photo':
   s['album_media']=[{'x':i} for i in range(album_count)] if album_count else None
   s['album_photo_count']=album_count
  if kind=='text':s['media_url']=''
  if kind=='video':s['watermark_required']=True
  rec={'draft_id':key,'status':'PRIVATE_SENT_CONFIRMED',
       'public_publication':'OFF','message_id':471,'media_type':kind,
       'telegram_photo_file_id':'A'*36}
  if album_count:
   rec.update(album_photo_count=album_count,
       telegram_photo_file_ids=['A'*35,'B'*35],
       album_message_ids=[469,470])
  (paths['st']/(key+'.json')).write_text(json.dumps(s),encoding='utf8')
  (paths['priv']/(key+'.json')).write_text(json.dumps(rec),encoding='utf8')
  return s,rec
 def click(key,action,userid=12345,private=True):
  u={'callback_query':{'data':'ne1:'+action+':'+key,
      'from':{'id':userid},
      'message':{'message_id':471,'chat':{'id':12345,'type':'private' if private else 'group'}}}}
  return cb.process_callback(u,mod)
 # 1: unauthorized action cannot create decision or publication.
 key='a'*24;stage(key,'photo')
 assert click(key,'accept',999)['status']=='EDITORIAL_USER_NOT_ALLOWED'
 assert click(key,'accept',private=False)['status']=='EDITORIAL_PRIVATE_CHAT_REQUIRED'
 assert not list(paths['dec'].iterdir())
 checks.append('UNAUTHORIZED_AND_NONPRIVATE_CALLBACK_DENIED')
 # 2: reject card never sends, repeat is idempotent.
 assert click(key,'reject')['status']=='EDITORIAL_REJECTED'
 assert click(key,'reject')['status']=='EDITORIAL_ALREADY_DECIDED'
 assert p.choose(act) is None
 checks.append('REJECT_AND_REPEAT_CALLBACK_IDEMPOTENT')
 # 3: accepted photo -> send once with footer, duplicate not selected.
 key='b'*24;stage(key,'photo')
 assert click(key,'accept')['status']=='EDITORIAL_ACCEPTED_NO_PUBLICATION'
 assert click(key,'accept')['status']=='EDITORIAL_ALREADY_DECIDED'
 assert p.choose(act) is not None
 assert p.publish_one()['status']=='PUBLIC_PUBLISHED_CONFIRMED'
 assert p.choose(act) is None
 assert len(calls)==1 and calls[0][0]=='sendPhoto'
 checks.append('PHOTO_ACCEPT_SEND_FOOTER_ONCE')
 # 4: complete album 2 photos -> one sendMediaGroup, with link.
 key='c'*24;stage(key,'photo',album_count=2)
 assert click(key,'accept')['status']=='EDITORIAL_ACCEPTED_NO_PUBLICATION'
 assert p.publish_one()['status']=='PUBLIC_PUBLISHED_CONFIRMED'
 assert len(calls)==2 and calls[-1][0]=='sendMediaGroup'
 checks.append('ALBUM_ALL_PHOTOS_AND_FOOTER_SEND_ONCE')
 # 5: text-only Accept with footer, no photo substitution.
 key='d'*24;stage(key,'text')
 assert click(key,'accept')['status']=='EDITORIAL_ACCEPTED_NO_PUBLICATION'
 assert t.publish_one()['status']=='PUBLIC_PUBLISHED_CONFIRMED'
 assert len(calls)==3 and calls[-1][0]=='sendMessage'
 checks.append('TEXT_ONLY_ACCEPT_FOOTER_SEND_ONCE')
 # 6: video requires explicit mode, WM accepted -> video receipt validated.
 key='e'*24;stage(key,'video')
 assert click(key,'accept')['status']=='VIDEO_EXPLICIT_MODE_REQUIRED'
 cb._watermark_after_video_accept=lambda key:{'status':'VIDEO_APPROVED_WATERMARK_HANDOFF_QUEUED_LOCAL'}
 assert click(key,'wm')['status']=='VIDEO_APPROVED_WATERMARK_HANDOFF_QUEUED_LOCAL'
 assert click(key,'wm')['status']=='VIDEO_APPROVED_WATERMARK_HANDOFF_QUEUED_LOCAL'
 movie=paths['render']/(key+'.mp4')
 movie.write_bytes(b'\x00\x00\x00\x18ftyp'+b'\x00'*1700)
 hexdigest=hashlib.sha256(movie.read_bytes()).hexdigest()
 render={'status':'NAS_WATERMARK_RENDERED','draft_id':key,
   'telegram_delivery':'NOT_SENT','publication':'OFF','output':str(movie),
   'video_mode':'wm','motion_qa':'PASS','verified_frames':37,
   'audio_integrity_qa':'PASS','watermark_visibility_qa':'PASS',
   'watermark_asset_sha256':v.APPROVED_LOGO_SHA256,
   'watermark_profile':v.WATERMARK_PROFILE,'sha256':hexdigest}
 (paths['render']/(key+'.json')).write_text(json.dumps(render),encoding='utf8')
 assert v.choose(p,act) is not None
 def fake_video_send(token,channel,video,caption):
  assert token=='OFFLINE_NO_REAL_TOKEN' and channel==act['chat_id']
  assert video==str(movie) and caption==globals()['caption']
  calls.append(('sendVideo',{}))
  return {'message_id':509,'chat':{'id':act['chat_id']}}
 v.send_mp4=fake_video_send
 assert v.publish()['status']=='PUBLIC_PUBLISHED_CONFIRMED'
 assert len(calls)==4 and calls[-1][0]=='sendVideo'
 checks.append('VIDEO_EXPLICIT_WM_SHA_PROFILE_AND_SEND_ONCE')
 # 7: stale approvals ignored, even if otherwise complete.
 key='f'*24;stage(key,'photo')
 assert click(key,'accept')['status']=='EDITORIAL_ACCEPTED_NO_PUBLICATION'
 dec=paths['dec']/(key+'.json');record=json.loads(dec.read_text());record['timestamp']=now-90000
 dec.write_text(json.dumps(record))
 assert p.choose(act) is None
 checks.append('STALE_APPROVAL_NEVER_PUBLISHED')
 # 8: uncertain public send receipt blocks all auto-retries.
 claim=paths['pub']/('9'*24+'.json')
 claim.write_text(json.dumps({'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY'}))
 try:p.choose(act)
 except RuntimeError as e:assert 'UNCERTAIN' in str(e)
 else:raise AssertionError('UNCERTAIN_PUBLIC_SEND_WAS_NOT_BLOCKED')
 checks.append('UNCERTAIN_PUBLIC_SEND_GLOBAL_PAUSE')
 # 9: native wrapper footer offset after emoji correctly encoded UTF-16.
 post,entities=footer.append_footer('💥 Новина')
 assert entities[1]['offset']==len('💥 Новина\n\n'.encode('utf-16-le'))//2
 checks.append('UTF16_BOLD_TEXT_LINK_FOOTER')
print(json.dumps({'status':'NEWS2_P1_LIVE_MODULES_ISOLATED_ACCEPTANCE_PASS',
 'tests':checks,'tests_passed':len(checks),
 'mocked_telegram_send_calls':len(calls),
 'real_telegram_calls':0,'nas_production_writes':0,
 'real_publications':0},ensure_ascii=False))
