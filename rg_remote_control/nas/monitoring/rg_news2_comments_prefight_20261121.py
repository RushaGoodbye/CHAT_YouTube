#!/usr/bin/env python3
"""RG NEWS2 comments read-only preflight, no publishing, no message edits, no pollers.
Verify linked discussions, bot edit permissions, eligible prior posts and actual
discussion message mapping. Never print tokens or private content.
"""
import collections,datetime as dt,json,os,pathlib,re,sys,urllib.request,urllib.error
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator';sys.path[:0]=[str(O),str(B)]
PUB=O/'news_rg_publication_receipts_v1'
LOG=O/'news_rg_continuous_callback.log'
def read(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>50000:return None
  a=json.loads(p.read_text('utf8'));return a if isinstance(a,dict) else None
 except Exception:return None
def scan_log():
 found=[]
 if LOG.is_file() and not LOG.is_symlink():
  with LOG.open(encoding='utf8',errors='replace') as f:
   for line in f:
    if 'is_automatic_forward' not in line and 'forward_from_message_id' not in line:continue
    try:
     obj=json.loads(line.partition(' ')[2])
     if isinstance(obj,dict):found.append({'channel_message_id':obj.get('forward_from_message_id'),
           'discussion_message_id':obj.get('message_id')})
    except Exception:pass
 return found[:15]
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 import news_rg_approved_publication_v1 as p
 token=p.credentials()
 gate=p.gate()
 channel=p.verify_channel(p.module(),token)
 channel_id=channel.get('chat_id')
 import news_rg_organic_post_v1 as composer
 import rg_moderation
 # Read-only Telegram API metadata call: getChat, no send, no poll
 args={'chat_id':str(channel_id)}
 url='https://api.telegram.org/bot'+token+'/getChat'
 request=urllib.request.Request(url,data=json.dumps(args).encode(),
      headers={'Content-Type':'application/json'})
 detail={}
 try:
  with urllib.request.urlopen(request,timeout=18) as r:obj=json.load(r)
  if obj.get('ok') is True:
   chat=obj.get('result') or {}
   detail={'status':'LINKED_DISCUSSION_GROUP_FOUND' if chat.get('linked_chat_id') else 'NO_LINKED_DISCUSSION_GROUP',
      'linked_chat_id':chat.get('linked_chat_id'),'channel_id':chat.get('id'),
      'channel_username':chat.get('username')}
  else:detail={'status':'CHANNEL_METADATA_API_REFUSED','error_code':obj.get('error_code')}
 except urllib.error.HTTPError as e:detail={'status':'CHANNEL_METADATA_HTTP_FAILED','http_status':e.code}
 except Exception as e:detail={'status':'CHANNEL_METADATA_UNAVAILABLE','error_class':type(e).__name__}
 receipts=[]
 for file in PUB.glob('*.json'):
  d=read(file)
  if not d or d.get('status')!='PUBLIC_PUBLISHED_CONFIRMED':continue
  mids=d.get('message_ids')
  if not isinstance(mids,list):mids=[d.get('message_id')]
  mids=[x for x in mids if type(x)==int and x>0]
  if not mids:continue
  receipts.append({'media_type':d.get('media_type'),'message_ids':mids,
     'own_channel_id':d.get('channel_id'),'draft_id':file.stem})
 last=sorted(receipts,key=lambda x:max(x['message_ids']),reverse=True)[:5]
 res={'status':'COMMENTS_LINK_PREFLIGHT','checked_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
 'channel':detail,'publisher_gate_channel_matches':channel_id==gate.get('chat_id'),
 'publisher_gate_bot_matches':channel.get('bot_id')==gate.get('bot_id'),
 'confirmed_receipts':len(receipts),'receipt_media_types':dict(collections.Counter(z['media_type'] for z in receipts)),
 'recent_post_ids':[{'post_ids':x['message_ids'],'type':x['media_type']} for x in last],
 'composer_keyboard_has_share': '📤 ПОДІЛИТИСЯ' in composer.keyboard(100)['inline_keyboard'][0][0]['text'],
 'composer_keyboard_has_subscribe':any('ПІДПИСАТИСЯ' in b.get('text','') for row in composer.keyboard(100)['inline_keyboard'] for b in row),
 'known_discussion_mappings_in_callback_log':scan_log(),
 'telegram_send_calls':0,'publications':0,'edits':0,'new_pollers':0}
 print(json.dumps(res,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','error_type':type(e).__name__,
  'reason':str(e)[:110] if str(e)=='SUDO_REQUIRED' else 'PREFLIGHT_FAILED',
  'telegram_send_calls':0,'publications':0,'edits':0}))
  sys.exit(2)
