#!/usr/bin/env python3
"""News2 P28: read-only confirm real moderation action captured by P25
and check queue/offset. No bot API, no changes or publication.
"""
import datetime,json,os,pathlib,sqlite3,sys
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 db=sqlite3.connect('file:'+str(B/'news.sqlite3')+'?mode=ro',uri=True,timeout=5)
 db.row_factory=sqlite3.Row
 last=sorted(O.glob('p25_updates_*.json'))[-5:]
 updates=[]
 for f in last:
  j=json.loads(f.read_text('utf-8'))
  for u in j.get('updates',[]):
   c=u.get('callback_query') or {}
   raw=c.get('data','')
   parts=str(raw).split(':')
   msg=c.get('message') or {}
   chat=msg.get('chat') or {}
   if len(parts)>=2 and parts[0]=='rg3':
    action=parts[1]
    mid=msg.get('message_id')
    found=db.execute('SELECT c.status candidate_status,d.state dispatch_state,c.id candidate_id FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id WHERE d.message_id=? LIMIT 1',(mid,)).fetchone()
    updates.append({'update_id':u.get('update_id'),'message_id':mid,'action':action,'private_chat':chat.get('type')=='private',
      'candidate_found':bool(found),
      'candidate_status':found['candidate_status'] if found else None,
      'dispatch_state':found['dispatch_state'] if found else None})
   elif parts[0]=='rgprobe25':
    updates.append({'update_id':u.get('update_id'),'message_id':msg.get('message_id'),'action':'test_probe'})
 saved=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
 pending=db.execute("""SELECT COUNT(*) n FROM moderation_dispatch d JOIN candidates c ON d.candidate_id=c.id WHERE d.state IN ('sent','send_uncertain') AND c.status IN ('awaiting_moderation','awaiting_photo_review')""").fetchone()['n']
 summary=[dict(r) for r in db.execute("""SELECT c.status candidate_status,d.state dispatch_state,COUNT(*) n FROM moderation_dispatch d JOIN candidates c ON d.candidate_id=c.id GROUP BY c.status,d.state""")]
 db.close()
 print(json.dumps({'status':'NEWS2_P28_REAL_BUTTON_AUDIT','checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'events':updates[-10:],'last_p25_archives':len(last),'offset':int(saved[0]) if saved else None,
   'queue_pending':pending,'queue_limit':3,'dispatch_summary':summary,
   'publication_gate_enabled':(B/'PUBLISH_ENABLED').exists(),'old_probation_scheduled':'RG_NEWS2_CALLBACK_PROBATION_V1' in pathlib.Path('/etc/crontab').read_text('utf-8',errors='replace'),
   'api_calls':0,'mutations':0,'channel_sends':0},ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'P28_BLOCKED','reason':str(e) if isinstance(e,RuntimeError) else type(e).__name__}))
  sys.exit(1)
