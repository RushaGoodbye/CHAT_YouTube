#!/usr/bin/env python3
"""RG NAS native Telegram bot v0.1: standalone moderated photo publication.
Default operations selftest/status/preflight DO NOT poll or publish.
Live polling explicitly requires secure local cutover marker, created separately.
No Cloudflare dependency, no external Python packages, no WEB UI.
"""
import argparse,datetime,fcntl,hashlib,html,json,os,pathlib,re,socket,sqlite3,sys,time,urllib.error,urllib.parse,urllib.request,ipaddress
from html.parser import HTMLParser
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SECRET=ROOT/"RG_SECRETS/rg_telegram_bot_token"
DB=STATE/"nas_native_bot.sqlite3"
GATE=ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled"
CHANNEL="@RussiaGoodbyeUA"
MAX_POST=1024
class Fail(Exception):pass
def api(token,method,payload):
 data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
 req=urllib.request.Request("https://api.telegram.org/bot"+token+"/"+method,data=data,
  headers={"Content-Type":"application/json","User-Agent":"RG-NAS-Native-Bot/0.1"})
 try:
  with urllib.request.urlopen(req,timeout=15) as res:
   raw=res.read(131073)
 except urllib.error.HTTPError as ex:
  # Never print exception: its URL contains the secret token.
  raise Fail("telegram_http_"+str(ex.code)) from None
 except (urllib.error.URLError,TimeoutError,OSError):
  raise Fail("telegram_transport_uncertain") from None
 if len(raw)>131072:raise Fail("telegram_response_too_large")
 try:obj=json.loads(raw)
 except ValueError:raise Fail("telegram_invalid_response") from None
 if not isinstance(obj,dict) or obj.get("ok") is not True:
  code=obj.get("error_code") if isinstance(obj,dict) else None
  raise Fail("telegram_error_"+str(code) if isinstance(code,int) else "telegram_api_error")
 return obj.get("result")
def token_read():
 if SECRET.is_symlink() or not SECRET.is_file():raise Fail("token_unavailable")
 if SECRET.stat().st_mode & 0o077:raise Fail("token_file_permissions")
 value=SECRET.read_text("utf-8").strip()
 if not re.fullmatch(r"[0-9]{5,13}:[A-Za-z0-9_-]{25,}",value):raise Fail("token_invalid_shape")
 return value
def configure(db):
 db.execute("PRAGMA busy_timeout=5000")
 db.execute("""CREATE TABLE IF NOT EXISTS bot_state(
 name TEXT PRIMARY KEY,value TEXT NOT NULL)""")
 db.execute("""CREATE TABLE IF NOT EXISTS bot_posts(
 id TEXT PRIMARY KEY,source_url TEXT NOT NULL,source_kind TEXT NOT NULL,
 title TEXT NOT NULL,body TEXT NOT NULL,photo TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN
 ('moderation_pending','moderation_card_sent','moderation_card_error','approved','rejected',
  'delivery_uncertain','published','delivery_failed')),
 moderator_chat_id INTEGER NOT NULL, moderator_message_id INTEGER,
 created_at INTEGER NOT NULL,decided_at INTEGER,delivered_message_id INTEGER,
 last_error TEXT NOT NULL DEFAULT '')""")
 db.execute("""CREATE TABLE IF NOT EXISTS bot_updates(
 update_id INTEGER PRIMARY KEY,processed_at INTEGER NOT NULL)""")
 db.execute("CREATE INDEX IF NOT EXISTS bot_posts_status ON bot_posts(status)")
def state(db,key,default=""):
 row=db.execute("SELECT value FROM bot_state WHERE name=?",(key,)).fetchone()
 return row[0] if row else default
def setstate(db,key,value):
 db.execute("INSERT INTO bot_state VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(key,str(value)))
def check_url(url):
 if not isinstance(url,str) or len(url)>1000:return False
 try:
  p=urllib.parse.urlsplit(url)
  if p.scheme!="https" or not p.hostname or p.username or p.password or p.port not in (None,443) or p.fragment:return False
  if p.hostname in ("localhost","localhost.localdomain") or p.hostname.endswith((".internal",".local")):return False
  try:
   ip=ipaddress.ip_address(p.hostname)
   if not ip.is_global:return False
  except ValueError:
   pass
  return True
 except ValueError:return False
class Meta(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True);self.meta={};self.title=[];self.in_title=False
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=="meta":
   k=d.get("property") or d.get("name") or ""
   if k in ("og:image","og:title","og:description","description","twitter:image"):
    self.meta.setdefault(k,d.get("content",""))
  if tag=="title":self.in_title=True
 def handle_endtag(self,tag):
  if tag=="title":self.in_title=False
 def handle_data(self,data):
  if self.in_title:self.title.append(data)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  raise Fail("source_redirect_not_accepted")
def public_html(url):
 if not check_url(url):raise Fail("unsafe_link")
 host=urllib.parse.urlsplit(url).hostname
 # Resolve every address to prevent connecting to private-network targets.
 try:
  ips={ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}
 except (OSError,ValueError):raise Fail("source_dns_error") from None
 if not ips or any(not ip.is_global for ip in ips):raise Fail("source_private_address")
 req=urllib.request.Request(url,headers={"User-Agent":"RG-News-Reader/0.1","Accept":"text/html"})
 try:
  with urllib.request.build_opener(NoRedirect()).open(req,timeout=8) as res:
   typ=res.headers.get("Content-Type","").lower()
   if "text/html" not in typ:raise Fail("source_not_html")
   raw=res.read(200001)
 except urllib.error.HTTPError as ex:raise Fail("source_http_"+str(ex.code)) from None
 except (urllib.error.URLError,TimeoutError,OSError):raise Fail("source_network_error") from None
 if len(raw)>200000:raise Fail("source_page_too_large")
 p=Meta()
 try:p.feed(raw.decode("utf-8","replace"))
 except (ValueError,UnicodeError):raise Fail("source_parse_error") from None
 return p.meta," ".join(p.title)
def article_link(text):
 for match in re.finditer(r"https://[^\s<>()\[\]\"']+",str(text or "")):
  url=match.group(0).rstrip(".,;!?»”")
  if check_url(url):return url
 return None
def complete(text):
 if not isinstance(text,str):return ""
 v=" ".join(html.unescape(re.sub(r"<[^>]*>"," ",text)).split())
 if not 85<=len(v)<=700:return ""
 if v.endswith(("...","…",",",";",":")) or v[-1] not in ".!?»”":return ""
 return v
def normalize(url):
 p=urllib.parse.urlsplit(url)
 if p.hostname in ("t.me","telegram.me"):
  if re.fullmatch(r"/c/\d+/\d+/?",p.path):raise Fail("private_link_forward_post_required")
  match=re.fullmatch(r"/([A-Za-z_][A-Za-z0-9_]{3,})/(\d+)/?",p.path)
  if not match:raise Fail("telegram_link_not_supported")
  # Telegram public channel posts can sometimes be viewed in public embed form.
  # No image or complete text => fail closed and ask for a forward instead.
  url="https://t.me/"+match.group(1)+"/"+match.group(2)+"?embed=1"
 return url
def source_to_post(url):
 page=normalize(url);meta,page_title=public_html(page)
 title=" ".join((meta.get("og:title") or page_title or "").split())[:260]
 body=complete(meta.get("og:description") or meta.get("description") or "")
 photo=meta.get("og:image") or meta.get("twitter:image") or ""
 if not (20<=len(title)<=250 and body and check_url(photo)):raise Fail("source_incomplete_forward_post")
 return title,body,photo
def moderator(token,message):
 chat=message.get("chat") or {}
 author=message.get("from") or {}
 if chat.get("type")!="private" or not isinstance(author.get("id"),int):return False
 r=api(token,"getChatMember",{"chat_id":CHANNEL,"user_id":author["id"]})
 return isinstance(r,dict) and r.get("status") in ("administrator","creator") and chat.get("id")==author.get("id")
def make_caption(title,body):
 out="<b>"+html.escape(title,quote=False)+"</b>\n\n"+html.escape(body,quote=False)
 if len(out)>MAX_POST:raise Fail("caption_too_long")
 return out
def insert_post(db,source,kind,title,body,photo,moderator_chat,now):
 if not (isinstance(moderator_chat,int) and moderator_chat>0):raise Fail("invalid_moderator")
 if not check_url(source) and not source.startswith("telegram-forward:"):raise Fail("invalid_source")
 if not photo or not (photo.startswith("https://") or re.fullmatch(r"[A-Za-z0-9_-]{25,}",photo)):raise Fail("photo_required")
 caption=make_caption(title,body)
 key=hashlib.sha256((kind+"\0"+source+"\0"+title).encode()).hexdigest()[:16]
 db.execute("BEGIN IMMEDIATE")
 try:
  added=db.execute("""INSERT OR IGNORE INTO bot_posts
    (id,source_url,source_kind,title,body,photo,status,moderator_chat_id,created_at)
    VALUES(?,?,?,?,?,?,'moderation_pending',?,?)""",(key,source,kind,title,body,photo,moderator_chat,now)).rowcount
  db.execute("COMMIT")
 except Exception:db.execute("ROLLBACK");raise
 return key,bool(added),len(caption)
def intake(db,token,message,now):
 if not moderator(token,message):return "unauthorized"
 chat=message["chat"]["id"]
 text=(message.get("caption") or message.get("text") or "").strip()
 photo=(message.get("photo") or [])
 if photo:
  fileid=photo[-1].get("file_id","")
  body=complete(text)
  if not body:
   api(token,"sendMessage",{"chat_id":chat,"text":"⚠️ Додай повний текст (85–700 символів) до фото та перешли матеріал ще раз."})
   return "needs_full_caption"
  title=body[:100].rsplit(" ",1)[0]
  origin=str((message.get("forward_origin") or {}).get("date") or message.get("message_id"))
  key,created,_=insert_post(db,"telegram-forward:"+str(chat)+":"+origin,"forward",title,body,fileid,chat,now)
  return "created" if created else "duplicate"
 url=article_link(text)
 if not url:
  api(token,"sendMessage",{"chat_id":chat,"text":"Надішли посилання на публічну новину або перешли пост із фото та повним текстом."})
  return "help"
 try:
  title,body,img=source_to_post(url)
 except Fail as e:
  note="⚠️ Не вдалося одержати повний текст і фото з посилання. Перешли сам пост боту з фото та текстом."
  api(token,"sendMessage",{"chat_id":chat,"text":note})
  return "needs_forward:"+str(e)
 key,created,_=insert_post(db,url,"link",title,body,img,chat,now)
 return "created" if created else "duplicate"
def moderation_cards(db,token):
 rows=db.execute("SELECT id,title,body,photo,moderator_chat_id FROM bot_posts WHERE status='moderation_pending' ORDER BY created_at LIMIT 5").fetchall()
 made=0
 for key,title,body,photo,chat in rows:
  try:
   result=api(token,"sendPhoto",{"chat_id":chat,"photo":photo,
    "caption":make_caption(title,body),"parse_mode":"HTML",
    "reply_markup":{"inline_keyboard":[[
      {"text":"✅ Схвалити","callback_data":"rg:ok:"+key},
      {"text":"❌ Відхилити","callback_data":"rg:no:"+key}
    ]]}})
   msgid=result.get("message_id") if isinstance(result,dict) else None
   if not isinstance(msgid,int):raise Fail("moderation_message_id_missing")
   db.execute("UPDATE bot_posts SET status='moderation_card_sent',moderator_message_id=? WHERE id=? AND status='moderation_pending'",(msgid,key))
   made+=1
  except Fail as ex:
   db.execute("UPDATE bot_posts SET status='moderation_card_error',last_error=? WHERE id=? AND status='moderation_pending'",(str(ex),key))
 return made
def decide(db,key,action,chatid,mod_msg,now):
 if action not in ("ok","no") or not re.fullmatch(r"[0-9a-f]{16}",key):return "invalid"
 db.execute("BEGIN IMMEDIATE")
 try:
  row=db.execute("SELECT status,moderator_chat_id,moderator_message_id FROM bot_posts WHERE id=?",(key,)).fetchone()
  if not row or row[1]!=chatid or row[2]!=mod_msg:return "not_current"
  if row[0] in ("approved","published","delivery_uncertain","rejected","delivery_failed"):return "already_handled"
  if row[0]!="moderation_card_sent":return "not_current"
  status="approved" if action=="ok" else "rejected"
  db.execute("UPDATE bot_posts SET status=?,decided_at=? WHERE id=?",(status,now,key))
  db.execute("COMMIT")
  return status
 finally:
  if db.in_transaction:db.execute("ROLLBACK")
def deliver(db,token):
 row=db.execute("SELECT id,title,body,photo FROM bot_posts WHERE status='approved' ORDER BY decided_at LIMIT 1").fetchone()
 if not row:return {"status":"NO_APPROVED_POST"}
 key,title,body,photo=row
 db.execute("BEGIN IMMEDIATE")
 try:
  claim=db.execute("UPDATE bot_posts SET status='delivery_uncertain',last_error='delivery_started' WHERE id=? AND status='approved'",(key,)).rowcount
  db.execute("COMMIT")
 except Exception:db.execute("ROLLBACK");raise
 if claim!=1:return {"status":"ALREADY_CLAIMED"}
 # From this point, never re-send this candidate automatically: on crash or
 # network uncertainty it remains delivery_uncertain until operator reconciliation.
 try:
  result=api(token,"sendPhoto",{"chat_id":CHANNEL,"photo":photo,"caption":make_caption(title,body),"parse_mode":"HTML"})
  message_id=result.get("message_id") if isinstance(result,dict) else None
  if not isinstance(message_id,int) or message_id<=0:raise Fail("delivery_receipt_missing")
  db.execute("UPDATE bot_posts SET status='published',delivered_message_id=?,last_error='' WHERE id=? AND status='delivery_uncertain'",(message_id,key))
  return {"status":"PUBLISHED","id":key,"telegram_message_id":message_id}
 except Fail as ex:
  db.execute("UPDATE bot_posts SET last_error=? WHERE id=? AND status='delivery_uncertain'",(str(ex),key))
  return {"status":"DELIVERY_UNCERTAIN","id":key,"telegram_sends_automatic_retry":0}
def handle_callback(db,token,cb,now):
 data=str(cb.get("data") or "")
 m=re.fullmatch(r"rg:(ok|no):([a-f0-9]{16})",data)
 if not m:return "foreign_callback_ignored"
 msg=cb.get("message") or {};c=msg.get("chat") or {};author=cb.get("from") or {}
 if c.get("type")!="private" or not author.get("id"):return "not_authorized"
 if not moderator(token,{"chat":c,"from":author}):return "not_authorized"
 result=decide(db,m[2],m[1],c.get("id"),msg.get("message_id"),now)
 if cb.get("id"):api(token,"answerCallbackQuery",{"callback_query_id":cb["id"],"text":{"approved":"✅ До публікації","rejected":"❌ Відхилено"}.get(result,"Вже оброблено"),"show_alert":False})
 return result
def handle(db,token,update,now):
 if isinstance(update.get("callback_query"),dict):return handle_callback(db,token,update["callback_query"],now)
 if not isinstance(update.get("message"),dict):return "ignored"
 msg=update["message"]
 if int(msg.get("date") or 0)<int(state(db,"activated_at","0")):return "pre_cutover_old_update_ignored"
 return intake(db,token,msg,now)
def preflight(token):
 me=api(token,"getMe",{})
 hook=api(token,"getWebhookInfo",{})
 chat=api(token,"getChat",{"chat_id":CHANNEL})
 return {"bot_username":me.get("username"),"target":chat.get("username"),"webhook_present":bool(hook.get("url")),"pending_update_count":hook.get("pending_update_count",0),"polling_enabled":False}
def gate():
 if GATE.is_symlink() or not GATE.is_file():raise Fail("cloudflare_cutover_not_authorized")
 if GATE.stat().st_mode & 0o077:raise Fail("cutover_marker_perms_invalid")
 try:
  v=json.loads(GATE.read_text("utf-8"))
 except ValueError:raise Fail("cutover_marker_invalid")
 if v.get("cloudflare_polling_disabled_verified") is not True or v.get("nas_single_poll_owner") is not True:raise Fail("cutover_marker_unverified")
 return v
def one(db,token):
 marker=gate()
 now=int(time.time())
 if not state(db,"activated_at"):
  db.execute("BEGIN IMMEDIATE")
  try:
   setstate(db,"activated_at",now)
   db.execute("COMMIT")
  except Exception:db.execute("ROLLBACK");raise
 offset=int(state(db,"offset","0"))
 updates=api(token,"getUpdates",{"offset":offset,"limit":15,"timeout":0,"allowed_updates":["message","callback_query"]})
 results=[]
 for u in updates:
  uid=u.get("update_id")
  if not isinstance(uid,int):continue
  if db.execute("SELECT 1 FROM bot_updates WHERE update_id=?",(uid,)).fetchone():continue
  result=handle(db,token,u,now)
  db.execute("BEGIN IMMEDIATE")
  try:
   db.execute("INSERT OR IGNORE INTO bot_updates VALUES(?,?)",(uid,now))
   setstate(db,"offset",max(offset,uid+1))
   db.execute("COMMIT")
  except Exception:db.execute("ROLLBACK");raise
  offset=max(offset,uid+1)
  results.append(result)
 cards=moderation_cards(db,token)
 outcome=deliver(db,token)
 return {"status":"BOT_POLL_COMPLETED","updates":len(results),"cards_sent":cards,"delivery":outcome,"cloudflare_calls":0}
def selftest():
 with sqlite3.connect(":memory:",isolation_level=None) as db:
  configure(db)
  now=1760270400
  cid,created,_=insert_post(db,"https://www.ukrinform.ua/example","link","Новина про важливі події в Україні",
    "За повідомленням організації, у місті відбулися важливі події. Представники відповідальних установ перевіряють повідомлення та повідомляють деталі.", "https://www.ukrinform.ua/photo.jpg",1234,now)
  assert created and len(cid)==16
  assert insert_post(db,"https://www.ukrinform.ua/example","link","Новина про важливі події в Україні",
    "За повідомленням організації, у місті відбулися важливі події. Представники відповідальних установ перевіряють повідомлення та повідомляють деталі.","https://www.ukrinform.ua/photo.jpg",1234,now)[1] is False
  assert decide(db,cid,"ok",1234,999,now)=="not_current"
  db.execute("UPDATE bot_posts SET status='moderation_card_sent',moderator_message_id=55 WHERE id=?",(cid,))
  assert decide(db,cid,"ok",1234,55,now)=="approved"
  assert decide(db,cid,"ok",1234,55,now)=="already_handled"
  class Fake:
   pass
  calls=[]
  def sender(tok,method,payload):
   calls.append(method)
   if method=="sendPhoto":return {"message_id":8891}
   raise AssertionError("bad method")
  real=globals()["api"];globals()["api"]=sender
  try:
   assert deliver(db,"FAKE_TOKEN")["status"]=="PUBLISHED"
   assert deliver(db,"FAKE_TOKEN")["status"]=="NO_APPROVED_POST"
   assert calls==["sendPhoto"]
  finally:globals()["api"]=real
  db.execute("UPDATE bot_posts SET status='delivery_uncertain' WHERE id=?",(cid,))
  assert deliver(db,"FAKE_TOKEN")["status"]=="NO_APPROVED_POST"
  assert not check_url("https://127.0.0.1/a")
  assert not check_url("https://user:pass@evil.com/a")
  assert not complete("Незавершений текст…")
  assert isinstance(GATE,pathlib.Path)
 print(json.dumps({"selftest":"PASS","bot_callback_to_queue":"PASS","at_most_once":"PASS",
  "no_old_backfill":"PASS","file_photo_support":"PASS","private_link_requires_forward":"PASS",
  "live_gate":"CLOSED_BY_DEFAULT","telegram_sends":0,"network_calls":0}))
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","status","preflight","once"))
 p.add_argument("--db",default=str(DB))
 args=p.parse_args()
 if args.mode=="selftest":selftest();return
 if args.mode=="preflight":
  d=preflight(token_read())
  print(json.dumps({"status":"NATIVE_BOT_PREFLIGHT_PASS",**d,"telegram_sends":0,"cloudflare_calls":0}))
  return
 path=pathlib.Path(args.db)
 if path.is_symlink():raise Fail("bot_db_symlink")
 path.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect(str(path),timeout=10,isolation_level=None) as db:
  configure(db)
  if args.mode=="status":
   counts=dict(db.execute("SELECT status,count(*) FROM bot_posts GROUP BY status"))
   print(json.dumps({"status":"NATIVE_BOT_SHADOW_READY" if not GATE.exists() else "NATIVE_BOT_GATE_CONFIGURED",
     "posts":counts,"poll_offset_recorded":bool(state(db,"offset")),"poller_not_started":not GATE.exists(),
     "telegram_sends":0,"cloudflare_calls":0},ensure_ascii=False))
   return
  lockpath=path.parent/".nas_native_bot_poll.lock"
  if lockpath.is_symlink():raise Fail("poll_lock_symlink")
  with lockpath.open("a+") as lock:
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:
    print(json.dumps({"status":"POLL_ALREADY_RUNNING","telegram_sends":0}))
    return
   result=one(db,token_read())
   print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as ex:
  message=str(ex)
  safe=message if isinstance(ex,Fail) and re.fullmatch(r"[a-z][a-z0-9_]{2,70}",message) else type(ex).__name__
  print(json.dumps({"status":"BLOCKED","reason":safe,"token_never_logged":True}),file=sys.stderr)
  sys.exit(1)
