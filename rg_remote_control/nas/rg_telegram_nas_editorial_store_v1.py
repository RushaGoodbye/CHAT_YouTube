#!/usr/bin/env python3
"""RG Telegram: local editorial drafts for manually reviewed complete posts.
No Cloudflare, Telegram sends or AI inference. Only SQLite.
Saving a draft always invalidates its previous approval binding.
"""
import argparse,hashlib,html,json,pathlib,re,sqlite3,sys,tempfile,time
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
def normalized(text):
 if not isinstance(text,str):raise ValueError("text_not_string")
 return " ".join(text.split()).strip()
def valid_body(body):
 body=normalized(body)
 if not 85<=len(body)<=700:raise ValueError("editorial_length_85_700")
 if body[-1:] not in ".!?»”" or re.search(r"(?:\.\.\.|…|[,;:])\s*$",body):raise ValueError("editorial_truncated")
 if "<" in body or ">" in body:raise ValueError("editorial_markup_forbidden")
 return body
def init(db):
 db.execute("PRAGMA busy_timeout=5000")
 db.execute("""CREATE TABLE IF NOT EXISTS nas_news_editorial_content(
   candidate_id TEXT PRIMARY KEY, review_event_id TEXT NOT NULL DEFAULT '',
   source_url TEXT NOT NULL, image_url TEXT NOT NULL,
   body TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0
    CHECK(verified IN (0,1)), updated_at INTEGER NOT NULL DEFAULT 0)""")
 db.execute("""CREATE TABLE IF NOT EXISTS nas_editorial_source_suggestions(
   candidate_id TEXT PRIMARY KEY, source_url TEXT NOT NULL,
   snippet TEXT NOT NULL, updated_at INTEGER NOT NULL)""")
def candidate_info(db,cid):
 if not isinstance(cid,str) or not re.fullmatch(r"[0-9a-f]{12}",cid):raise ValueError("invalid_candidate_id")
 row=db.execute("SELECT headline,image_url,source_url,status,review_event_id FROM moderation_projection WHERE candidate_id=?",(cid,)).fetchone()
 if not row:raise ValueError("candidate_missing")
 if not row[0] or not row[1] or not row[2]:raise ValueError("candidate_missing_photo_or_source")
 return row
def save(db,cid,body,now=None):
 now=int(time.time()) if now is None else int(now)
 if not isinstance(body,str) or len(body)>1000:raise ValueError("invalid_text_length")
 text=normalized(body)
 if len(text)>700:raise ValueError("invalid_text_length")
 row=candidate_info(db,cid)
 _,image,source,status,_=row
 if status not in ("awaiting_review","deferred","ready_shadow"):raise ValueError("candidate_not_editable")
 db.execute("BEGIN IMMEDIATE")
 try:
  db.execute("""INSERT INTO nas_news_editorial_content(candidate_id,review_event_id,source_url,image_url,body,verified,updated_at)
    VALUES(?,'',?,?,?,0,?)
    ON CONFLICT(candidate_id) DO UPDATE SET
    review_event_id='',source_url=excluded.source_url,image_url=excluded.image_url,
    body=excluded.body,verified=0,updated_at=excluded.updated_at""",(cid,source,image,text,now))
  db.execute("COMMIT")
 except Exception:
  db.execute("ROLLBACK");raise
 return {"status":"DRAFT_SAVED","candidate_id":cid,"characters":len(text),"verified":False,"telegram_sends":0}
def bind(db,cid):
 row=candidate_info(db,cid)
 title,image,source,status,eid=row
 if status!="ready_shadow" or not isinstance(eid,str) or not eid.startswith("nasreview:"+cid+":") or not eid.endswith(":approved"):
  raise ValueError("local_approval_missing")
 draft=db.execute("SELECT source_url,image_url,body FROM nas_news_editorial_content WHERE candidate_id=?",(cid,)).fetchone()
 if not draft or draft[:2]!=(source,image):raise ValueError("draft_source_mismatch")
 body=valid_body(draft[2])
 if not 20<=len(title.strip())<=300:raise ValueError("title_invalid")
 count=db.execute("UPDATE nas_news_editorial_content SET review_event_id=?,verified=1 WHERE candidate_id=? AND source_url=? AND image_url=? AND body=?",
   (eid,cid,source,image,body)).rowcount
 if count!=1:raise ValueError("draft_changed")
 return {"status":"EDITORIAL_APPROVAL_BOUND","candidate_id":cid,"verified":True,"telegram_sends":0}
def visible(db,cid):
 if not re.fullmatch(r"[0-9a-f]{12}",cid):return ("","",False)
 current=db.execute("SELECT body,review_event_id,verified FROM nas_news_editorial_content WHERE candidate_id=?",(cid,)).fetchone()
 suggestion=db.execute("SELECT snippet FROM nas_editorial_source_suggestions WHERE candidate_id=?",(cid,)).fetchone()
 return (current[0] if current else "",suggestion[0] if suggestion else "",bool(current and current[2]==1))
def source_snippet(value):
 # Reference material, never auto-sent. Short to avoid copying a full article.
 if not isinstance(value,str):return ""
 value=html.unescape(re.sub(r"<[^>]*>"," ",value))
 value=" ".join(value.split())
 return value[:240].rsplit(" ",1)[0] if len(value)>240 else value
def seed(db,rows,now=None):
 now=int(time.time()) if now is None else int(now)
 init(db);changed=0
 for row in rows:
  cid=row.get("candidate_id");src=row.get("source_url");summary=row.get("summary")
  if not isinstance(cid,str) or not re.fullmatch(r"[0-9a-f]{12}",cid):continue
  if not isinstance(src,str) or not src.startswith("https://") or hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]!=cid:continue
  match=db.execute("SELECT source_url FROM moderation_projection WHERE candidate_id=?",(cid,)).fetchone()
  if not match or match[0]!=src:continue
  snippet=source_snippet(summary)
  if len(snippet)<30:continue
  db.execute("""INSERT INTO nas_editorial_source_suggestions VALUES(?,?,?,?)
    ON CONFLICT(candidate_id) DO UPDATE SET snippet=excluded.snippet,updated_at=excluded.updated_at
    WHERE nas_editorial_source_suggestions.source_url=excluded.source_url""",(cid,src,snippet,now))
  changed+=1
 return changed
def selftest():
 with sqlite3.connect(":memory:",isolation_level=None) as db:
  db.execute("""CREATE TABLE moderation_projection(candidate_id TEXT PRIMARY KEY,headline TEXT,image_url TEXT,
     source_url TEXT,status TEXT,review_event_id TEXT)""")
  init(db)
  url="https://example.org/news";cid=hashlib.sha256(url.encode("utf-8")).hexdigest()[:12];title="Достовірна новина зі значущими подробицями"
  img="https://example.org/photograph.jpg"
  db.execute("INSERT INTO moderation_projection VALUES(?,?,?,?,?,?)",(cid,title,img,url,"awaiting_review",None))
  assert visible(db,cid)==("","",False)
  seed(db,[{"candidate_id":cid,"source_url":url,"summary":"<p>У місті оприлюднено нові подробиці підтвердженої події, інформація надійшла від офіційного джерела.</p>"}],100)
  assert "нові подробиці" in visible(db,cid)[1] and visible(db,cid)[0]==""
  assert seed(db,[{"candidate_id":"abcdefabcdef","source_url":url,"summary":"Цей фрагмент не повинен потрапити до іншої новини за чужим ідентифікатором."}],101)==0
  body="За офіційними відомостями, у місті стало відомо про важливу подію. Відповідальні служби перевіряють обставини та повідомлять додаткові деталі."
  assert save(db,cid,body,now=100)["verified"] is False
  try:bind(db,cid)
  except ValueError:pass
  else:raise AssertionError("draft_approved_without_operator")
  eid="nasreview:"+cid+":123:approved"
  db.execute("UPDATE moderation_projection SET status='ready_shadow',review_event_id=? WHERE candidate_id=?",(eid,cid))
  assert bind(db,cid)["verified"] is True
  assert visible(db,cid)[2] is True
  assert save(db,cid,body+" Уточнення.",now=101)["verified"] is False
  assert visible(db,cid)[2] is False
  db.execute("UPDATE moderation_projection SET status='rejected' WHERE candidate_id=?",(cid,))
  try:save(db,cid,body,now=102)
  except ValueError:pass
  else:raise AssertionError("rejected_candidate_writable")
  assert source_snippet("<b>Тест</b> &amp; важлива подія")=="Тест & важлива подія"
  for bad in ("Коротко.","Неповна новина…","Фраза без завершення,"):
   try:valid_body(bad)
   except ValueError:pass
   else:raise AssertionError("invalid_body_accepted")
 print(json.dumps({"status":"EDITORIAL_STORE_SELFTEST_PASS","manual_only":"PASS","approval_bound":"PASS",
  "edit_revokes_verified":"PASS","no_auto_publish":"PASS","telegram_sends":0,"network_calls":0}))
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","initialize","status","seed"))
 p.add_argument("--db",default=str(DB));p.add_argument("--inbox",default="/volume1/docker/RG_TELEGRAM_STATE/candidate_inbox.jsonl")
 a=p.parse_args()
 if a.mode=="selftest":selftest();return
 path=pathlib.Path(a.db)
 if path.is_symlink() or not path.is_file():raise ValueError("db_missing")
 with sqlite3.connect(str(path),isolation_level=None,timeout=10) as db:
  init(db)
  loaded=0
  if a.mode=="seed":
   source=pathlib.Path(a.inbox)
   if not source.is_file() or source.is_symlink() or source.stat().st_size>2097152:raise ValueError("rss_inbox_missing")
   rows=[]
   with source.open("r",encoding="utf-8") as f:
    for line in f:
     if line.strip():rows.append(json.loads(line))
   loaded=seed(db,rows)
  print(json.dumps({"status":"EDITORIAL_STORE_READY","suggestions_saved_this_run":loaded,
   "draft_count":db.execute("SELECT count(*) FROM nas_news_editorial_content").fetchone()[0],
   "source_reference_count":db.execute("SELECT count(*) FROM nas_editorial_source_suggestions").fetchone()[0],
   "telegram_sends":0,"cloudflare_calls":0}))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","reason":type(exc).__name__+":"+str(exc)[:100],"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
