#!/usr/bin/env python3
"""NEWS2 front observer: remove unproven missing-post alarm from limited Telegram HTML feed.
Does not touch Telegram bot, public sends, or pinned V6.
"""
import ast,datetime,hashlib,json,os,pathlib,tempfile
P=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_required_slots_observer_v1.py')
OLD="""  rows.append({'slot':name,'status':'NOT_FOUND_IN_PUBLIC_FEED'})
  # External feed has limited history; it is a warning, not proof of failure.
  if key not in state['notified']:
   issues.append(name)
   if alert:state['notified'][key]=int(now.timestamp())
"""
NEW="""  # The public Telegram HTML view is truncated and is NOT an authoritative
  # publication ledger. Do not send a false missing-post alarm for 'front'.
  # Keep a visible unverified status so an authoritative Cloudflare KV audit
  # can still investigate missing scheduled content.
  if name=='front':
   rows.append({'slot':name,'status':'UNVERIFIED_PUBLIC_HTML',
                'absence_not_proven':True,
                'requires_cloudflare_kv_to_distinguish':True})
   continue
  rows.append({'slot':name,'status':'NOT_FOUND_IN_PUBLIC_FEED'})
  # External feed has limited history; it is a warning, not proof of failure.
  if key not in state['notified']:
   issues.append(name)
   if alert:state['notified'][key]=int(now.timestamp())
"""
def run():
 if P.is_symlink() or not P.is_file():raise RuntimeError('OBSERVER_NOT_SAFE_FILE')
 src=P.read_text('utf8')
 if NEW in src and OLD not in src:
  print(json.dumps({'status':'ALREADY_PATCHED','publication_calls':0}));return
 if src.count(OLD)!=1:raise RuntimeError('OBSERVER_ANCHOR_CHANGED')
 upd=src.replace(OLD,NEW)
 ast.parse(upd,filename=P.name)
 # Existing notifier must remain unmodified; never disable other alerts.
 for t in ('def fetch():','def observe(alert=False):','bot.api(\'sendMessage\'','requires_cloudflare_kv_to_distinguish'):
  if t not in upd:raise RuntimeError('GUARD_MISSING')
 b=P.parent/'news_rg_front_observer_backups'
 if b.is_symlink():raise RuntimeError('BACKUP_SYMLINK')
 b.mkdir(mode=0o700,exist_ok=True)
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 copy=b/('front_observer_before_'+stamp+'.py')
 if copy.exists():raise RuntimeError('BACKUP_COLLISION')
 copy.write_bytes(src.encode('utf8'));os.chmod(copy,0o600)
 fd,tmp=tempfile.mkstemp(prefix='.front_observer_',dir=P.parent)
 try:
  os.fchmod(fd,P.stat().st_mode&0o777)
  with os.fdopen(fd,'w',encoding='utf8') as f:
   f.write(upd);f.flush();os.fsync(f.fileno())
  os.replace(tmp,P)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 try:
  ast.parse(P.read_text('utf8'))
  if P.read_text('utf8')!=upd:raise RuntimeError('WRITE_MISMATCH')
 except Exception:
  P.write_text(src,'utf8')
  raise
 print(json.dumps({'status':'FRONT_FALSE_ALERT_OBSERVER_FIXED',
   'backup':copy.name,'front_status':'UNVERIFIED_PUBLIC_HTML',
   'cloudflare_kv_verification':'STILL_REQUIRED','telegram_calls':0,
   'publications':0,'pinned_modules_changed':0},ensure_ascii=False))
if __name__=='__main__':run()
