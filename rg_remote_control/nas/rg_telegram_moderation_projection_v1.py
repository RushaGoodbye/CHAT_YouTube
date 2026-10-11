#!/usr/bin/env python3
"""RG Telegram NAS: build review-to-publish shadow decisions from intake events.
No Telegram token or network calls; projection is transactional and idempotent.
"""
import argparse,json,pathlib,sqlite3,tempfile,time
DB="/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3"
def setup(db):
 db.execute("PRAGMA busy_timeout=5000")
 db.execute("""CREATE TABLE IF NOT EXISTS moderation_projection (
 candidate_id TEXT PRIMARY KEY, headline TEXT, image_url TEXT,
 source_url TEXT, decision TEXT NOT NULL DEFAULT 'pending',
 review_event_id TEXT, review_at INTEGER,
 status TEXT NOT NULL DEFAULT 'awaiting_review',
 CHECK(decision IN ('pending','approved','rejected','deferred')),
 CHECK(status IN ('awaiting_review','ready_shadow','rejected','deferred','invalid'))
 )""")
 db.execute("""CREATE TABLE IF NOT EXISTS moderation_projection_checkpoint (
 key TEXT PRIMARY KEY, value INTEGER NOT NULL
 )""")
 db.execute("""CREATE TABLE IF NOT EXISTS shadow_publish_intents (
 candidate_id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'shadow_only', created_at INTEGER NOT NULL,
 CHECK(status='shadow_only')
 )""")
def process(db):
 db.execute("BEGIN IMMEDIATE")
 try:
  lastrow=db.execute("SELECT value FROM moderation_projection_checkpoint WHERE key='events_rowid'").fetchone()
  last=lastrow[0] if lastrow else 0
  rows=db.execute("SELECT rowid,event_id,kind,payload FROM events WHERE rowid>? AND kind IN ('news_candidate','moderation_decision') ORDER BY rowid",(last,)).fetchall()
  processed=0
  for rid,eid,kind,raw in rows:
   try:p=json.loads(raw)
   except (TypeError,ValueError):continue
   if kind=="news_candidate":
    cid=p.get("candidate_id")
    if not isinstance(cid,str) or not cid or not p.get("headline") or not p.get("image_url"):continue
    db.execute("""INSERT OR IGNORE INTO moderation_projection(candidate_id,headline,image_url,source_url) VALUES(?,?,?,?)""",(cid,p["headline"],p["image_url"],p.get("source_url")))
   else:
    cid=p.get("candidate_id");choice=p.get("decision")
    if not cid or choice not in ("approved","rejected","deferred"):continue
    review_time=p.get("reviewed_at")
    try:review_time=int(review_time)
    except (ValueError,TypeError):review_time=0
    # Fail closed if no content matching this candidate, or previously reviewed.
    row=db.execute("SELECT decision,review_at,headline,image_url FROM moderation_projection WHERE candidate_id=?",(cid,)).fetchone()
    if row and review_time>0 and (row[1] is None or review_time>row[1]):
     state={"approved":"ready_shadow","rejected":"rejected","deferred":"deferred"}[choice]
     db.execute("UPDATE moderation_projection SET decision=?,review_event_id=?,review_at=?,status=? WHERE candidate_id=?",(choice,eid,review_time,state,cid))
     if choice=="approved":
      db.execute("INSERT OR IGNORE INTO shadow_publish_intents(candidate_id,event_id,created_at) VALUES(?,?,?)",(cid,eid,int(time.time())))
      # A later rejection invalidates readiness but intent remains audit-only.
   processed+=1
  if rows:db.execute("INSERT INTO moderation_projection_checkpoint(key,value) VALUES('events_rowid',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rows[-1][0],))
  db.execute("COMMIT")
  return processed
 except Exception:
  db.execute("ROLLBACK");raise
def status(db):
 return {"projection":dict(db.execute("SELECT status,count(*) FROM moderation_projection GROUP BY status").fetchall()),"publish_intents_shadow":db.execute("SELECT count(*) FROM shadow_publish_intents").fetchone()[0],"delivery_enabled":False}
def selftest():
 with tempfile.TemporaryDirectory() as tmp:
  with sqlite3.connect(str(pathlib.Path(tmp)/"test.sqlite"),isolation_level=None) as db:
   db.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created_at INTEGER,state TEXT)")
   setup(db)
   def ev(i,k,p):db.execute("INSERT INTO events VALUES(?,?,?,?,?)",(i,k,json.dumps(p),100,"shadow"))
   ev("a","news_candidate",{"candidate_id":"c1","headline":"Actual news","image_url":"https://example.org/photo.jpg"})
   ev("b","moderation_decision",{"candidate_id":"c1","decision":"approved","reviewed_at":100})
   assert process(db)==2
   assert status(db)["publish_intents_shadow"]==1
   assert process(db)==0
   ev("c","moderation_decision",{"candidate_id":"c1","decision":"rejected","reviewed_at":101})
   assert process(db)==1
   assert status(db)["projection"]=={"rejected":1}
   ev("d","moderation_decision",{"candidate_id":"unknown","decision":"approved","reviewed_at":102})
   assert process(db)==1
   assert status(db)["publish_intents_shadow"]==1
 print(json.dumps({"selftest":"PASS","dedupe":"PASS","rejection_override":"PASS","unknown_candidate_fail_closed":"PASS","sending_enabled":False}))
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","initialize","once","status"]);p.add_argument("--db",default=DB);a=p.parse_args()
 if a.mode=="selftest":selftest();return
 if not pathlib.Path(a.db).is_file():raise SystemExit("BLOCKED: database missing")
 with sqlite3.connect(a.db,isolation_level=None,timeout=10) as db:
  setup(db)
  n=process(db) if a.mode=="once" else 0
  print(json.dumps({"status":"SHADOW_PROJECTION_OK","processed":n,**status(db)}))
if __name__=="__main__":main()
