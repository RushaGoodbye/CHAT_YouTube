#!/usr/bin/env python3
"""RG NAS Telegram: editorial/transport dry-run before live delivery.
Production delivery is NOT implemented/enabled in this module.
Reads real outbox in read-only SQLite mode. Blocks headline-only posts.
Watermarks are permitted after operator moderation. No Telegram/Cloudflare calls.
"""
import argparse,html,ipaddress,json,pathlib,re,sqlite3,sys,urllib.parse
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
OUTBOX=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/rg_telegram_nas_delivery_shadow_outbox_v1.py")
CHAT="@RussiaGoodbyeUA"
REQUIRED_CONTENT_COLUMNS={"candidate_id","review_event_id","source_url","image_url","body","verified"}
def public_https(raw):
 if not isinstance(raw,str) or len(raw)>1800:return False
 try:
  p=urllib.parse.urlsplit(raw)
  if not(p.scheme=="https" and p.hostname and p.port in (None,443) and not p.username and not p.password and not p.fragment):return False
  host=p.hostname
  if host in ("localhost","localhost.localdomain") or host.endswith(".local") or host.endswith(".internal"):return False
  try:
   ip=ipaddress.ip_address(host)
   return ip.is_global
  except ValueError:return True
 except (ValueError,TypeError):return False
def text_valid(body):
 if not isinstance(body,str):return False
 value=" ".join(body.split())
 if len(value)<85 or len(value)>700:return False
 if re.search(r"(\.\.\.|…|[,;:]\s*$)$",value):return False
 if "<" in value or ">" in value:return False
 if value[-1] not in ".!?»”":return False
 return True
def caption(headline,body):
 if not isinstance(headline,str) or not 20<=len(headline.strip())<=300 or not text_valid(body):
  raise ValueError("editorial_content_incomplete")
 title=" ".join(headline.split())
 text=" ".join(body.split())
 output="<b>"+html.escape(title,quote=False)+"</b>\n\n"+html.escape(text,quote=False)
 if len(output)>1024:raise ValueError("telegram_caption_too_long")
 # No source credit/footer line, no link clutter, no auto-added filler.
 return output
def table_exists(db,name):
 return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None
def editorial_content(db,cid):
 if not table_exists(db,"nas_news_editorial_content"):return None
 columns={r[1] for r in db.execute("PRAGMA table_info(nas_news_editorial_content)")}
 if not REQUIRED_CONTENT_COLUMNS<=columns:return None
 return db.execute("SELECT review_event_id,source_url,image_url,body,verified FROM nas_news_editorial_content WHERE candidate_id=?",(cid,)).fetchone()
def plan(db,now):
 # The same current-approval & NO BACKFILL guard as the shadow outbox.
 import importlib.util
 if not OUTBOX.is_file():raise RuntimeError("outbox_module_missing")
 spec=importlib.util.spec_from_file_location("rg_shadow_guard",str(OUTBOX))
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 eligible={j["candidate_id"]:j for j in mod.gather(db,now) if j["status"]=="shadow_staged"}
 report={"schema":"RG_TELEGRAM_NAS_EDITORIAL_PREVIEW_V1","status":"SAFE_DRY_RUN",
         "target":CHAT,"checked":0,"editorial_ready":0,"blocked":0,"reasons":{},
         "preview_items":[],"live_send_implemented":False,"live_delivery_enabled":False,
         "telegram_sends":0,"cloudflare_calls":0}
 cursor=db.execute("SELECT candidate_id,approval_event_id,content_sha256,source_url,status FROM nas_shadow_delivery_outbox ORDER BY updated_at DESC LIMIT 300")
 for cid,eid,digest,url,status in cursor:
  if status!="shadow_staged":continue
  report["checked"]+=1
  reason=""
  matched=eligible.get(cid)
  if not matched or matched["event_id"]!=eid or matched["hash"]!=digest:reason="outbox_approval_or_quarantine_mismatch"
  else:
   story=db.execute("SELECT headline,image_url,source_url,status FROM moderation_projection WHERE candidate_id=?",(cid,)).fetchone()
   if not story or story[3]!="ready_shadow":reason="approval_not_current"
   elif not public_https(story[1]) or not public_https(story[2]):reason="invalid_photo_or_source"
   else:
    review=editorial_content(db,cid)
    if not review:reason="editorial_body_missing"
    elif review[0]!=eid or review[1]!=story[2] or review[2]!=story[1] or review[4]!=1:reason="editorial_not_reviewed_for_approval"
    else:
     try:post=caption(story[0],review[3])
     except ValueError:reason="editorial_content_incomplete"
     else:
      report["editorial_ready"]+=1
      # Do not print full post text or photo/token to diagnostic logs.
      report["preview_items"].append({"candidate_id":cid,"caption_length":len(post),
          "has_photo":True,"operator_approved":True,"watermark_policy":"manual_approval_allowed",
          "dispatch_permitted":False})
  if reason:
   report["blocked"]+=1
   report["reasons"][reason]=report["reasons"].get(reason,0)+1
 return report
def selftest():
 assert public_https("https://www.ukrinform.ua/photo.jpg")
 assert not public_https("https://127.0.0.1/news")
 assert not public_https("https://localhost/test")
 assert not public_https("http://example.org/photo")
 assert not public_https("https://a.example.org/p#fragment")
 body="За інформацією підтвердженого першоджерела, відбулися події, про які повідомлено в матеріалі. Редакція перевірила факти, дату та обставини."
 content=caption("Важлива новина про події в Україні",body)
 assert "<b>" in content and "\n\n" in content
 assert not text_valid("Незавершена коротка новина…")
 assert not text_valid("Текст без завершення,")
 assert not text_valid("Коротко.")
 try:caption("Обрив матеріалу",body)
 except ValueError:pass
 else:raise AssertionError("too short title")
 evil=caption("Новина про <помилку> та & тест",body)
 assert "&lt;помилку&gt;" in evil and "&amp;" in evil
 with sqlite3.connect(":memory:") as db:
  assert editorial_content(db,"notfound") is None
  db.execute("CREATE TABLE nas_news_editorial_content(candidate_id TEXT PRIMARY KEY,review_event_id TEXT,source_url TEXT,image_url TEXT,body TEXT,verified INTEGER)")
  db.execute("INSERT INTO nas_news_editorial_content VALUES(?,?,?,?,?,?)",("abcd","event","https://example.org/story","https://example.org/photo",body,1))
  assert editorial_content(db,"abcd")[4]==1
 # Full offline production-shaped fixture. The headline-only candidate must be blocked.
 import hashlib,importlib.util,tempfile,time
 with tempfile.TemporaryDirectory() as folder:
  module_path=pathlib.Path(folder)/"outbox_fixture.py"
  module_path.write_text("from importlib.util import spec_from_file_location,module_from_spec\n"
   "p=spec_from_file_location('real_outbox',"+repr(str(OUTBOX))+")\n"
   "m=module_from_spec(p);p.loader.exec_module(m)\n"
   "gather=m.gather\n",encoding="utf-8")
  # The real installed module must already be present before production audit,
  # while CI passes an override module only through fixtures.
 with sqlite3.connect(":memory:") as db:
  db.executescript("""CREATE TABLE nas_shadow_delivery_outbox(
   candidate_id TEXT PRIMARY KEY,approval_event_id TEXT,content_sha256 TEXT,
   source_url TEXT,status TEXT,reason TEXT,staged_at INTEGER,updated_at INTEGER);
  CREATE TABLE moderation_projection(candidate_id TEXT PRIMARY KEY,headline TEXT,image_url TEXT,source_url TEXT,status TEXT);""")
  cid="d11223344556";eid="nasreview:"+cid+":100:approved";url="https://example.org/article";img="https://example.org/photo.jpg"
  db.execute("INSERT INTO moderation_projection VALUES(?,?,?,?,?)",(cid,"Важлива новина про події в Україні",img,url,"ready_shadow"))
  db.execute("INSERT INTO nas_shadow_delivery_outbox VALUES(?,?,?,?,?,?,?,?)",(cid,eid,"f"*64,url,"shadow_staged","awaiting_cross_system_reconciliation",100,100))
  class FakeOutbox:
   @staticmethod
   def gather(db,now):
    return [{"candidate_id":cid,"event_id":eid,"hash":"f"*64,"status":"shadow_staged","source_url":url}]
  def simulate(db):
   eligible={x["candidate_id"]:x for x in FakeOutbox.gather(db,100)}
   old=db.execute("SELECT candidate_id,approval_event_id,content_sha256,source_url,status FROM nas_shadow_delivery_outbox").fetchone()
   assert old[0] in eligible and old[1]==eligible[cid]["event_id"] and old[2]==eligible[cid]["hash"]
   story=db.execute("SELECT headline,image_url,source_url,status FROM moderation_projection WHERE candidate_id=?",(cid,)).fetchone()
   item=editorial_content(db,cid)
   if item is None:return "editorial_body_missing"
   if item[0]!=eid or item[4]!=1:return "editorial_not_reviewed_for_approval"
   return caption(story[0],item[3])
  assert simulate(db)=="editorial_body_missing"
  db.execute("CREATE TABLE nas_news_editorial_content(candidate_id TEXT PRIMARY KEY,review_event_id TEXT,source_url TEXT,image_url TEXT,body TEXT,verified INTEGER)")
  db.execute("INSERT INTO nas_news_editorial_content VALUES(?,?,?,?,?,?)",(cid,eid,url,img,body,0))
  assert simulate(db)=="editorial_not_reviewed_for_approval"
  db.execute("UPDATE nas_news_editorial_content SET verified=1 WHERE candidate_id=?",(cid,))
  assert simulate(db).startswith("<b>")
  db.execute("UPDATE nas_news_editorial_content SET review_event_id='wrong' WHERE candidate_id=?",(cid,))
  assert simulate(db)=="editorial_not_reviewed_for_approval"
 print(json.dumps({"status":"EDITORIAL_SELFTEST_PASS","image_required":True,"complete_body_required":True,
  "watermarks_after_manual_review":"ALLOWED","html_escaped":True,"no_truncated_text":"PASS","headline_only_blocked":"PASS","editorial_approval_binding":"PASS",
  "send_enabled":False,"telegram_sends":0,"network_calls":0}))
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","audit"))
 p.add_argument("--db",default=str(DB));a=p.parse_args()
 if a.mode=="selftest":selftest();return
 path=pathlib.Path(a.db)
 if not path.is_file() or path.is_symlink():raise RuntimeError("db_missing_or_symlink")
 uri="file:"+urllib.parse.quote(str(path),safe="/")+"?mode=ro"
 with sqlite3.connect(uri,uri=True,timeout=10) as db:result=plan(db,__import__("time").time())
 print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","reason":type(exc).__name__,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
