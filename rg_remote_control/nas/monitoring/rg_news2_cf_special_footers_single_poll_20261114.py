#!/usr/bin/env python3
"""NEWS2 Cloudflare source-only atomic update. No deploy, no Telegram calls.

Removes branded footer from minute silence and Kyiv start/clear notices.
Changes split visual+native poll into ONE native poll message. Single-message
explainer with an image remains unchanged. Exact old SHA256 checks and backups.
"""
import datetime,hashlib,json,os,stat,sys,tempfile
from pathlib import Path

ALERT=Path('/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src/index.js')
HUB=Path('/volume1/docker/RG_CONTENT_DEPLOY/cloudflare-content-hub/src/index.js')
OLD={
 str(ALERT):'4ccaf4a7dd5dfc982a9f78218105909ee9f7a6dcfdfd429bdd9559141211c878',
 str(HUB):'39474c68ed2fbba08a6ca40621b7c53422271613c6f321828f3c7eba6b7aae70'
}
DIR=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator/rg_news2_release_backups_v7/cf_footers_single_poll_20261114')
RECEIPT=DIR/'receipt.json'
START='async function sendPollWithVisual(env, built, now, existingVisualMessageId = 0) {'
END='async function sendPhoto(env, built, now) {'
SINGLE_POLL='''async function sendPollWithVisual(env, built, now, existingVisualMessageId = 0) {
  // Telegram native poll cannot carry an attached photo; send ONE
  // self-contained poll instead of the previous image + reply pair.
  if (String(built?.cardKey || "") !== "poll") throw new Error("poll_cardKey_missing");
  validateScheduledPublication(built, "poll");
  assertCurrentContentSlot("poll", now.dateKey);
  const result = await telegramJson(env, "sendPoll", {
    chat_id: env.TELEGRAM_CHAT_ID,
    question: "📊 ПИТАННЯ ДНЯ — " + now.dateText + "\\n\\n" + built.question,
    options: built.options,
    is_anonymous: true,
    allows_multiple_answers: false,
    reply_markup: {
      inline_keyboard: [[{
        text: "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ",
        url: "https://links.rginfoua.pp.ua/",
      }]],
    },
  });
  const messageId = Number(result.message_id || 0);
  if (!messageId) throw new Error("Telegram returned no message_id for standalone poll");
  return { messageId, visualMessageId: 0 };
}
'''
class Stop(ValueError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def safe(p):
 st=p.lstat()
 owner_ok=(st.st_uid==0 or (p==ALERT and st.st_uid==p.parent.lstat().st_uid and stat.S_ISDIR(p.parent.lstat().st_mode)))
 if not stat.S_ISREG(st.st_mode) or not owner_ok or not 1000<=st.st_size<=400000:
  raise Stop('UNSAFE_SOURCE_'+p.name)
 return p.read_bytes()
def once(s,a,b,label):
 if s.count(a)!=1:raise Stop('PATCH_SOURCE_DRIFT_'+label)
 return s.replace(a,b,1)
def patch(before):
 a=before[str(ALERT)].decode('utf8');h=before[str(HUB)].decode('utf8')
 a=once(a,'form.append("caption", \'<b><a href="https://links.rginfoua.pp.ua/">УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ "РАША ГУДБАЙ"</a></b>\');',
           'form.append("caption", "");','minute_silence_footer')
 a=once(a,'form.append("caption", (kind === "clear" ? clearCaption(item) : startCaption(item))+"\\n\\n"+\'<b><a href="https://links.rginfoua.pp.ua/">УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ "РАША ГУДБАЙ"</a></b>\');',
           'form.append("caption", kind === "clear" ? clearCaption(item) : startCaption(item));','air_alert_footer')
 if h.count(START)!=1 or h.count(END)!=1:raise Stop('POLL_BOUNDARY_DRIFT')
 p=h.index(START);q=h.index(END,p)
 between=h[p:q]
 if ('sendPoll' not in between or 'sendPhoto' not in between or
     'visualMessageId' not in between):raise Stop('POLL_OLD_CODE_UNRECOGNIZED')
 h=h[:p]+SINGLE_POLL+'\n'+h[q:]
 if h.count('async function sendPollWithVisual')!=1 or h.count(END)!=1:
  raise Stop('POLL_NEW_CODE_INVALID')
 if 'reply_to_message_id: visualMessageId' in h:raise Stop('OLD_SPLIT_POLL_REMAINS')
 return {str(ALERT):a.encode('utf8'),str(HUB):h.encode('utf8')}
def preflight():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 if DIR.exists() or DIR.is_symlink():raise Stop('RELEASE_ALREADY_USED')
 old={}
 for f,digest in OLD.items():
  b=safe(Path(f))
  if sha(b)!=digest:raise Stop('LIVE_WORKER_SOURCE_CHANGED_'+Path(f).parent.name)
  old[f]=b
 return old,patch(old)
def atomic(p,b,mode):
 fd,t=tempfile.mkstemp(prefix='.rg_cf_safe_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(t,p)
 finally:
  if os.path.exists(t):os.unlink(t)
def apply():
 old,new=preflight()
 DIR.mkdir(parents=True,mode=0o700)
 for i,(k,v) in enumerate(old.items()):
  atomic(DIR/('original_worker_'+str(i)+'.js'),v,0o600)
  if sha(safe(DIR/('original_worker_'+str(i)+'.js')))!=OLD[k]:
   raise Stop('BACKUP_VERIFICATION_FAILED')
 done=[]
 try:
  for k,v in new.items():
   p=Path(k);mode=(0o644 if p==ALERT else stat.S_IMODE(p.stat().st_mode))
   done.append((p,mode))
   atomic(p,v,mode)
   if sha(safe(p))!=sha(v):raise Stop('INSTALL_HASH_MISMATCH_'+p.name)
  receipt={'status':'SOURCE_PATCHED_QA_PASS_DEPLOY_PENDING',
    'release':'RG_NEWS2_CF_FOOTER_AND_SINGLE_POLL_20261114',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'new_source_hashes':{k:sha(v) for k,v in new.items()},
    'backup_verified':True,'cloudflare_deployed':False,
    'telegram_calls':0,'publications':0}
  atomic(RECEIPT,(json.dumps(receipt,sort_keys=True)+'\n').encode('utf8'),0o600)
  return receipt
 except Exception:
  for p,mode in reversed(done):atomic(p,old[str(p)],mode)
  if any(sha(safe(Path(k)))!=digest for k,digest in OLD.items()):
   raise Stop('SOURCE_ROLLBACK_VERIFICATION_FAILED')
  raise
def selftest():
 assert len(OLD)==2 and all(len(x)==64 for x in OLD.values())
 assert SINGLE_POLL.count('telegramJson(env, "sendPoll"')==1
 assert 'sendPhoto' not in SINGLE_POLL
 print('NEWS2_CF_SINGLE_POLL_AND_SPECIAL_FOOTER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:selftest()
  elif mode==['preflight']:
   old,new=preflight()
   print(json.dumps({'status':'PREFLIGHT_PASS',
    'new_hashes':{k:sha(v) for k,v in new.items()},
    'cloudflare_deployments':0,'telegram_calls':0,'publications':0}))
  elif mode==['apply']:print(json.dumps(apply(),sort_keys=True))
  else:raise Stop('UNKNOWN_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:170],
    'cloudflare_deployments':0,'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
