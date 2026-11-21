#!/usr/bin/env python3
"""READ ONLY: check ability to receive linked discussion-group auto-forwards.
One Bot API getChat/getChatMember; no updates polling, no edits/posts.
"""
import datetime,json,os,pathlib,sys,urllib.request,urllib.error
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=B/'operator'
sys.path[:0]=[str(O),str(B)]
def call(token,method,data):
 req=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,
 data=json.dumps(data).encode('utf8'),headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=15) as r:
   obj=json.load(r)
  return obj.get('result') if obj.get('ok') is True else {'error_code':obj.get('error_code')}
 except urllib.error.HTTPError as e:return {'error_code':e.code}
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 import news_rg_approved_publication_v1 as pub
 token=pub.credentials()
 channel=pub.verify_channel(pub.module(),token)
 gate=pub.gate()
 if channel.get('bot_id')!=gate.get('bot_id') or channel.get('chat_id')!=gate.get('chat_id'):raise RuntimeError('CHANNEL_IDENTITY_GATE_MISMATCH')
 group=call(token,'getChat',{'chat_id':channel['chat_id']})
 if not isinstance(group,dict) or not isinstance(group.get('linked_chat_id'),int):
  raise RuntimeError('LINKED_GROUP_NOT_FOUND')
 groupid=group['linked_chat_id']
 detail=call(token,'getChat',{'chat_id':groupid})
 member=call(token,'getChatMember',{'chat_id':groupid,'user_id':channel['bot_id']})
 output={'status':'DISCUSSION_BOT_ACCESS_PREFLIGHT',
 'group_id':groupid,'group_type':detail.get('type') if isinstance(detail,dict) else None,
 'group_has_public_username':bool(detail.get('username')) if isinstance(detail,dict) else False,
 'group_username':detail.get('username') if isinstance(detail,dict) else None,
 'bot_membership':member.get('status') if isinstance(member,dict) else None,
 'bot_can_manage_chat':member.get('can_manage_chat') if isinstance(member,dict) else None,
 'get_chat_error':detail.get('error_code') if isinstance(detail,dict) else None,
 'member_error':member.get('error_code') if isinstance(member,dict) else None,
 'bot_id':channel['bot_id'],
 'no_poller_started':True,'telegram_messages_sent':0,'edits':0,'publications':0}
 print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','error_type':type(e).__name__,'reason':str(e)[:100] if str(e)=='SUDO_REQUIRED' else 'PREFLIGHT_FAILED','edits':0,'publications':0}))
  sys.exit(2)
