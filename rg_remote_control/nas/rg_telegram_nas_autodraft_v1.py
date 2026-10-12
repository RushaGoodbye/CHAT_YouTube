#!/usr/bin/env python3
"""RG Telegram NAS: conservative automatic editorial DRAFTS from source RSS summaries.
No AI/network/cost. Never approves, sends, edits an existing draft, or bypasses
NO BACKFILL. Uses only complete source sentences; if uncertain, leaves it manual.
"""
import argparse,hashlib,json,pathlib,re,sqlite3,sys,time,urllib.parse
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
MAX_AGE=36*3600
MAX_BATCH=100
def clean(v):
 return " ".join(v.split()).strip() if isinstance(v,str) else ""
def source_guard(cid,src):
 if not isinstance(cid,str) or not re.fullmatch(r"[a-f0-9]{12}",cid):return False
 if not isinstance(src,str) or len(src)>1800:return False
 try:
  p=urllib.parse.urlsplit(src)
  return p.scheme=="https" and p.hostname in ("www.ukrinform.ua","www.pravda.com.ua") and not p.username and not p.password and p.port in (None,443) and hashlib.sha256(src.encode()).hexdigest()[:12]==cid
 except ValueError:return False
def source_sentences(snippet):
 """Return only full sentences already present in the RSS reference; never finish fragments."""
 value=clean(snippet)
 if len(value)<85 or len(value)>400:return ""
 if re.search(r"[<>]|\bhttps?://|\b(?:читать|читати\s+далі|детальніше)\b",value,re.I):return ""
 # Periods between numerals and abbreviations do not generally have whitespace.
 sentences=re.findall(r"[^.!?]+[.!?](?=\s|$)",value)
 selected=[];size=0
 for raw in sentences:
  sentence=clean(raw)
  if not sentence:continue
  if len(sentence)<35:continue
  if sentence[0] in ",.;:":continue
  if len(sentence)>400:break
  if size+len(sentence)+1>500:break
  selected.append(sentence);size+=len(sentence)+1
 text=" ".join(selected)
 if not 85<=len(text)<=500:return ""
 if re.search(r"\.{3,}$|[,;:]$",text):return ""
 return text
def init(db):
 db.execute("PRAGMA busy_timeout=5000")
 db.execute("""CREATE TABLE IF NOT EXISTS nas_editorial_autodraft_metadata(
 candidate_id TEXT PRIMARY KEY, source_url TEXT NOT NULL, status TEXT NOT NULL
 CHECK(status='draft_unverified'), created_at INTEGER NOT NULL, origin TEXT NOT NULL
 CHECK(origin='rss_complete_sentences'))""")
def latest_dates(db):
 seen={}
 for (raw,) in db.execute("SELECT payload FROM events WHERE kind='news_candidate' ORDER BY rowid DESC LIMIT 15000"):
  try:d=json.loads(raw)
  except (ValueError,TypeError):continue
  if not isinstance(d,dict):continue
  cid=d.get("candidate_id");ts=d.get("detected_at")
  if isinstance(cid,str) and cid not in seen and isinstance(ts,int) and not isinstance(ts,bool):
   seen[cid]=ts
 return seen
def process(db,now=None,limit=MAX_BATCH):
 now=int(time.time()) if now is None else int(now)
 if not isinstance(limit,int) or not 1<=limit<=MAX_BATCH:raise ValueError("limit_invalid")
 names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 required={"events","moderation_projection","nas_editorial_source_suggestions","nas_news_editorial_content","nas_delivery_pre_cutover_quarantine"}
 if not required<=names:raise RuntimeError("editorial_prerequisites_missing")
 init(db)
 stats={"schema":"RG_NAS_RSS_AUTODRAFT_V1","status":"AUTODRAFT_UNVERIFIED_READY","scanned":0,
  "created":0,"needs_more_source":0,"skipped_existing":0,"skipped_quarantine":0,
  "skipped_non_pending":0,"skipped_stale":0,"unverified_drafts":0,
  "operator_approval_required":True,"live_delivery_enabled":False,"telegram_sends":0,"cloudflare_calls":0}
 db.execute("BEGIN IMMEDIATE")
 try:
  dates=latest_dates(db)
  quarantined_ids={r[0] for r in db.execute("SELECT candidate_id FROM nas_delivery_pre_cutover_quarantine")}
  quarantined_urls={r[0] for r in db.execute("SELECT source_url FROM nas_delivery_pre_cutover_quarantine")}
  rows=db.execute("""SELECT p.candidate_id,p.source_url,p.image_url,p.status,s.snippet
    FROM moderation_projection p JOIN nas_editorial_source_suggestions s ON s.candidate_id=p.candidate_id
    AND s.source_url=p.source_url
    ORDER BY p.rowid DESC LIMIT ?""",(limit,)).fetchall()
  for cid,src,img,status,snippet in rows:
   stats["scanned"]+=1
   if status not in ("awaiting_review","deferred"):
    stats["skipped_non_pending"]+=1;continue
   if cid in quarantined_ids or src in quarantined_urls:
    stats["skipped_quarantine"]+=1;continue
   if not source_guard(cid,src) or not isinstance(img,str) or not img.startswith("https://"):
    stats["needs_more_source"]+=1;continue
   stamp=dates.get(cid)
   if not isinstance(stamp,int) or not now-MAX_AGE<=stamp<=now+300:
    stats["skipped_stale"]+=1;continue
   if db.execute("SELECT 1 FROM nas_news_editorial_content WHERE candidate_id=?",(cid,)).fetchone():
    stats["skipped_existing"]+=1;continue
   text=source_sentences(snippet)
   if not text:
    stats["needs_more_source"]+=1;continue
   result=db.execute("""INSERT OR IGNORE INTO nas_news_editorial_content
     (candidate_id,review_event_id,source_url,image_url,body,verified,updated_at)
     VALUES(?,'',?,?,?,0,?)""",(cid,src,img,text,now))
   if result.rowcount==1:
    db.execute("""INSERT OR IGNORE INTO nas_editorial_autodraft_metadata
      VALUES(?,?,'draft_unverified',?,'rss_complete_sentences')""",(cid,src,now))
    stats["created"]+=1
   else:stats["skipped_existing"]+=1
  stats["unverified_drafts"]=db.execute("""SELECT count(*) FROM nas_editorial_autodraft_metadata m
    JOIN nas_news_editorial_content c ON c.candidate_id=m.candidate_id
    WHERE c.verified=0""").fetchone()[0]
  db.execute("COMMIT")
 except Exception:
  db.execute("ROLLBACK");raise
 return stats
def selftest():
 url="https://www.ukrinform.ua/rubric-society/123456.html"
 cid=hashlib.sha256(url.encode()).hexdigest()[:12]
 example="У місті оприлюднили нові дані щодо ситуації після повідомлення екстрених служб. За інформацією місцевої влади, відповідальні установи перевіряють обставини події."
 assert source_guard(cid,url)
 assert not source_guard(cid,url.replace("ukrinform.ua","attacker.example"))
 assert source_sentences(example).endswith(".")
 assert len(source_sentences(example))>=85
 assert source_sentences(example+" Незавершена частина без крапки")==example
 assert source_sentences("Обрив речення без фінальної крапки")==""
 with sqlite3.connect(":memory:",isolation_level=None) as db:
  db.executescript("""CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT);
 CREATE TABLE moderation_projection(candidate_id TEXT PRIMARY KEY,source_url TEXT,image_url TEXT,status TEXT);
 CREATE TABLE nas_editorial_source_suggestions(candidate_id TEXT PRIMARY KEY,source_url TEXT,snippet TEXT,updated_at INTEGER);
 CREATE TABLE nas_news_editorial_content(candidate_id TEXT PRIMARY KEY,review_event_id TEXT,
 source_url TEXT,image_url TEXT,body TEXT,verified INTEGER,updated_at INTEGER);
 CREATE TABLE nas_delivery_pre_cutover_quarantine(candidate_id TEXT PRIMARY KEY,source_url TEXT,captured_at INTEGER);""")
  now=1760270400
  db.execute("INSERT INTO events VALUES(?,?,?)",("nasnews:v2:"+cid,"news_candidate",json.dumps({"candidate_id":cid,"detected_at":now-600})))
  db.execute("INSERT INTO moderation_projection VALUES(?,?,?,?)",(cid,url,"https://www.ukrinform.ua/photo.jpg","awaiting_review"))
  db.execute("INSERT INTO nas_editorial_source_suggestions VALUES(?,?,?,?)",(cid,url,example,now))
  assert process(db,now)["created"]==1
  assert db.execute("SELECT verified FROM nas_news_editorial_content WHERE candidate_id=?",(cid,)).fetchone()[0]==0
  assert process(db,now)["created"]==0
  assert process(db,now)["skipped_existing"]==1
  db.execute("DELETE FROM nas_news_editorial_content")
  db.execute("DELETE FROM nas_editorial_autodraft_metadata")
  db.execute("INSERT INTO nas_delivery_pre_cutover_quarantine VALUES(?,?,?)",(cid,url,now))
  assert process(db,now)["created"]==0
  assert process(db,now)["skipped_quarantine"]==1
  db.execute("DELETE FROM nas_delivery_pre_cutover_quarantine")
  db.execute("UPDATE moderation_projection SET status='ready_shadow'")
  assert process(db,now)["skipped_non_pending"]==1
  db.execute("UPDATE moderation_projection SET status='awaiting_review'")
  assert process(db,now+MAX_AGE+3601)["skipped_stale"]==1
 print(json.dumps({"selftest":"PASS","complete_sentences_only":"PASS","original_facts_only":"PASS",
  "existing_drafts_preserved":"PASS","no_backfill":"PASS","stale_filtered":"PASS",
  "never_auto_approve":"PASS","telegram_sends":0,"network_calls":0}))
def main():
 p=argparse.ArgumentParser()
 p.add_argument("mode",choices=("selftest","once"))
 p.add_argument("--db",default=str(DB));p.add_argument("--limit",type=int,default=MAX_BATCH)
 args=p.parse_args()
 if args.mode=="selftest":selftest();return
 path=pathlib.Path(args.db)
 if path.is_symlink() or not path.is_file():raise RuntimeError("db_missing_or_symlink")
 with sqlite3.connect(str(path),timeout=12,isolation_level=None) as db:
  result=process(db,limit=args.limit)
 print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","reason":type(exc).__name__,
    "live_delivery_enabled":False,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
