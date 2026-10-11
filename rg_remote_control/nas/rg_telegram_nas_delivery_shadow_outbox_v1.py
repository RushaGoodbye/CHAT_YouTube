#!/usr/bin/env python3
"""RG Telegram NAS: shadow-only publication outbox with revocation.
No Telegram token, API calls, external sends or Cloudflare credentials.
Never activates delivery; all staged items explicitly require CF reconciliation.
"""
import argparse,hashlib,json,pathlib,sqlite3,sys,tempfile,time,urllib.parse
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
MAX_AGE=36*3600
def valid_https(raw):
 if not isinstance(raw,str) or not raw or len(raw)>1800:return False
 try:
  p=urllib.parse.urlsplit(raw)
  return p.scheme=="https" and bool(p.hostname) and not p.username and not p.password and not p.fragment and p.port in (None,443)
 except ValueError:return False
def decode(raw):
 try:
  value=json.loads(raw)
  return value if isinstance(value,dict) else {}
 except (TypeError,ValueError):return {}
def setup(db):
 db.execute("PRAGMA busy_timeout=5000")
 db.execute("""CREATE TABLE IF NOT EXISTS nas_shadow_delivery_outbox(
  candidate_id TEXT PRIMARY KEY,approval_event_id TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,source_url TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('shadow_staged','blocked')),
  reason TEXT NOT NULL,staged_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)""")
 db.execute("CREATE INDEX IF NOT EXISTS nas_shadow_delivery_outbox_status ON nas_shadow_delivery_outbox(status)")
def required(db):
 names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 need={"events","moderation_projection","shadow_publish_intents","shadow_event_receipts"}
 if not need<=names:raise RuntimeError("stage1_tables_missing")
def verified_receipt(db,eid,kind,source,payload):
 # The NAS events table intentionally has NO source column. Source is captured
 # in the deduplication hash in shadow_event_receipts by the intake module.
 row=db.execute("SELECT payload_sha256 FROM shadow_event_receipts WHERE event_id=?",(eid,)).fetchone()
 if not row:return False
 expected=hashlib.sha256((kind+"\0"+source+"\0"+payload).encode("utf-8")).hexdigest()
 return row[0]==expected
def decision_event(db,cid,eid,review_at):
 row=db.execute("SELECT kind,payload FROM events WHERE event_id=?",(eid,)).fetchone()
 if row is None:return False
 kind,payload=row
 d=decode(payload)
 return (kind=="moderation_decision"
  and eid=="nasreview:"+cid+":"+str(review_at)+":approved"
  and verified_receipt(db,eid,kind,"nas-operator-review",payload)
  and d.get("candidate_id")==cid and d.get("decision")=="approved"
  and d.get("reviewed_at")==review_at and d.get("reason_code")=="operator_verified")
def latest_news(db,cid,headline,image,source,now):
 rows=db.execute("SELECT event_id,kind,payload FROM events WHERE kind='news_candidate' ORDER BY rowid DESC LIMIT 5000")
 for eid,kind,raw in rows:
  d=decode(raw)
  if d.get("candidate_id")!=cid or d.get("headline")!=headline or d.get("source_url")!=source or d.get("image_url")!=image:continue
  if not (eid in ("nasnews:"+cid,"nasnews:v2:"+cid)):continue
  if not verified_receipt(db,eid,kind,"nas-local-spool",raw):continue
  ts=d.get("detected_at")
  if isinstance(ts,int) and not isinstance(ts,bool) and now-MAX_AGE<=ts<=now+300:return d
 return None
def gather(db,now):
 required(db)
 intents={c:(ev,st) for c,ev,st in db.execute("SELECT candidate_id,event_id,status FROM shadow_publish_intents")}
 seen_urls=set();planned=[]
 for cid,title,img,src,decision,status,eid,review_at in db.execute(
    "SELECT candidate_id,headline,image_url,source_url,decision,status,review_event_id,review_at FROM moderation_projection ORDER BY candidate_id"):
  intent=intents.get(cid)
  reason=""
  if status!="ready_shadow" or decision!="approved":reason="approval_revoked_or_pending"
  elif not intent or intent!=(eid,"shadow_only"):reason="intent_review_mismatch"
  elif not isinstance(eid,str) or not eid.startswith("nasreview:"+cid+":"):reason="review_not_local_operator"
  elif not decision_event(db,cid,eid,review_at):reason="review_event_unverified"
  elif not title or not valid_https(src) or not valid_https(img):reason="invalid_photo_or_link"
  elif not latest_news(db,cid,title,img,src,now):reason="news_record_stale_or_mismatch"
  elif src in seen_urls:reason="duplicate_approved_source"
  if not reason:seen_urls.add(src)
  if intent or status=="ready_shadow":
   snapshot=json.dumps({"candidate_id":cid,"headline":title,"photo":img,"source":src,"approval_event":eid},sort_keys=True,ensure_ascii=False,separators=(",",":"))
   digest=hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
   planned.append({"candidate_id":cid,"event_id":eid or "NO_APPROVAL",
     "hash":digest,"source_url":src or "",
     "status":"shadow_staged" if not reason else "blocked",
     "reason":reason or "awaiting_cross_system_reconciliation"})
 return planned
def stage(db,now=None):
 now=int(time.time()) if now is None else int(now)
 setup(db)
 db.execute("BEGIN IMMEDIATE")
 try:
  plan=gather(db,now)
  known={row[0]:row for row in db.execute("SELECT candidate_id,approval_event_id,content_sha256,status,reason FROM nas_shadow_delivery_outbox")}
  changed=0;unchanged=0
  for job in plan:
   cid=job["candidate_id"]
   data=(job["event_id"],job["hash"],job["status"],job["reason"])
   existing=known.get(cid)
   if existing and existing[1:]==data:
    unchanged+=1;continue
   if existing:
    db.execute("""UPDATE nas_shadow_delivery_outbox SET approval_event_id=?,content_sha256=?,source_url=?,
      status=?,reason=?,updated_at=? WHERE candidate_id=?""",
      (job["event_id"],job["hash"],job["source_url"],job["status"],job["reason"],now,cid))
   else:
    db.execute("""INSERT INTO nas_shadow_delivery_outbox VALUES(?,?,?,?,?,?,?,?)""",
      (cid,job["event_id"],job["hash"],job["source_url"],job["status"],job["reason"],now,now))
   changed+=1
  planned_ids={j["candidate_id"] for j in plan}
  # Previously staged jobs whose approval vanished must be blocked, never silently delivered.
  for cid in set(known)-planned_ids:
   old=known[cid]
   if old[3]!="blocked" or old[4]!="approval_revoked_or_pending":
    db.execute("UPDATE nas_shadow_delivery_outbox SET status='blocked',reason='approval_revoked_or_pending',updated_at=? WHERE candidate_id=?",(now,cid))
    changed+=1
  db.execute("COMMIT")
 except Exception:
  db.execute("ROLLBACK")
  raise
 return {"changed":changed,"unchanged":unchanged,"planned":len(plan)}
def report(db,now=None):
 now=int(time.time()) if now is None else int(now)
 counts=dict(db.execute("SELECT status,count(*) FROM nas_shadow_delivery_outbox GROUP BY status"))
 by_reason=dict(db.execute("SELECT reason,count(*) FROM nas_shadow_delivery_outbox GROUP BY reason"))
 return {"schema":"RG_NAS_DELIVERY_SHADOW_OUTBOX_V1","status":"SHADOW_OUTBOX_READY",
  "staged":counts.get("shadow_staged",0),"blocked":counts.get("blocked",0),
  "reason_counts":by_reason,
  "cross_system_receipts_verified":False,"cloudflare_previous_delivery_checked":False,
  "live_delivery_enabled":False,"telegram_sends":0,"cloudflare_calls":0}
def selftest():
 now=1760212800
 with tempfile.TemporaryDirectory() as tmp:
  with sqlite3.connect(str(pathlib.Path(tmp)/"test.sqlite"),isolation_level=None) as db:
   # Exactly the NAS Stage 1 schema (no events.source column).
   db.execute("""CREATE TABLE events(
     event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,
     created_at INTEGER,state TEXT)""")
   db.execute("""CREATE TABLE shadow_event_receipts(
     event_id TEXT PRIMARY KEY,payload_sha256 TEXT NOT NULL,
     first_seen_at INTEGER NOT NULL)""")
   db.execute("""CREATE TABLE moderation_projection(
    candidate_id TEXT PRIMARY KEY,headline TEXT,image_url TEXT,source_url TEXT,
    decision TEXT,status TEXT,review_event_id TEXT,review_at INTEGER)""")
   db.execute("CREATE TABLE shadow_publish_intents(candidate_id TEXT PRIMARY KEY,event_id TEXT,status TEXT)")
   def ingest(eid,kind,source,payload):
    raw=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":"))
    digest=hashlib.sha256((kind+"\0"+source+"\0"+raw).encode("utf-8")).hexdigest()
    db.execute("INSERT INTO events VALUES(?,?,?,?,?)",(eid,kind,raw,now,"shadow"))
    db.execute("INSERT INTO shadow_event_receipts VALUES(?,?,?)",(eid,digest,now))
   cid="abcde0123456";eid="nasreview:"+cid+":"+str(now)+":approved"
   title="Підтверджена новина з фото";img="https://example.org/photo.jpg";url="https://example.org/news"
   ingest("nasnews:v2:"+cid,"news_candidate","nas-local-spool",{"candidate_id":cid,"headline":title,"image_url":img,"source_url":url,"detected_at":now-180})
   ingest(eid,"moderation_decision","nas-operator-review",{"candidate_id":cid,"decision":"approved","reviewed_at":now,"reason_code":"operator_verified"})
   db.execute("INSERT INTO moderation_projection VALUES(?,?,?,?,?,?,?,?)",(cid,title,img,url,"approved","ready_shadow",eid,now))
   db.execute("INSERT INTO shadow_publish_intents VALUES(?,?,?)",(cid,eid,"shadow_only"))
   assert stage(db,now)["changed"]==1
   assert report(db)["staged"]==1
   assert stage(db,now)["changed"]==0
   # Tampered event must be blocked even when projection still looks approved.
   db.execute("UPDATE events SET payload=? WHERE event_id=?",(json.dumps({"candidate_id":cid,"decision":"approved","reviewed_at":now,"reason_code":"operator_verified"}),eid))
   assert stage(db,now)["changed"]==1
   assert dict(db.execute("SELECT reason,count(*) FROM nas_shadow_delivery_outbox GROUP BY reason"))["review_event_unverified"]==1
   db.execute("DELETE FROM events WHERE event_id=?",(eid,))
   ingest2=json.dumps({"candidate_id":cid,"decision":"approved","reviewed_at":now,"reason_code":"operator_verified"},sort_keys=True,ensure_ascii=False,separators=(",",":"))
   # Restoring the exact original serialized payload reestablishes the proof.
   db.execute("INSERT INTO events VALUES(?,?,?,?,?)",(eid,"moderation_decision",ingest2,now,"shadow"))
   assert stage(db,now)["changed"]==1
   assert report(db)["staged"]==1
   db.execute("UPDATE moderation_projection SET decision='rejected',status='rejected'")
   db.execute("DELETE FROM shadow_publish_intents")
   assert stage(db,now)["changed"]==1
   assert report(db)["blocked"]==1
   db.execute("UPDATE moderation_projection SET decision='approved',status='ready_shadow'")
   db.execute("INSERT INTO shadow_publish_intents VALUES(?,?,?)",(cid,eid,"shadow_only"))
   assert stage(db,now+MAX_AGE+3600)["changed"]==1
   assert dict(db.execute("SELECT reason,count(*) FROM nas_shadow_delivery_outbox GROUP BY reason"))["news_record_stale_or_mismatch"]==1
   assert report(db)["live_delivery_enabled"] is False
 print(json.dumps({"selftest":"PASS","production_events_schema":"PASS","receipt_provenance":"PASS",
    "dedup":"PASS","tamper_detection":"PASS","revocation":"PASS","expiration":"PASS",
    "cloudflare_receipts_gate":"CLOSED","telegram_sends":0,"network_calls":0}))
def main():
 p=argparse.ArgumentParser()
 p.add_argument("mode",choices=("selftest","stage","status"))
 p.add_argument("--db",default=str(DB))
 args=p.parse_args()
 if args.mode=="selftest":selftest();return
 path=pathlib.Path(args.db)
 if not path.is_file() or path.is_symlink():raise RuntimeError("database_missing_or_symlink")
 with sqlite3.connect(str(path),timeout=8,isolation_level=None) as db:
  if args.mode=="stage":
   result=stage(db)
   print(json.dumps({"stage":result,**report(db)},ensure_ascii=False))
  else:
   setup(db)
   print(json.dumps(report(db),ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","error_class":type(exc).__name__,
    "reason":str(exc)[:120],"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
