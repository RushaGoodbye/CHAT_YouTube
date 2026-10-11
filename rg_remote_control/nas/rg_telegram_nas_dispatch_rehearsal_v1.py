#!/usr/bin/env python3
"""RG NAS dispatcher rehearsal only. NEVER sends Telegram or reads bot credentials.
Exclusive at-most-once claim is exercised exclusively in temporary SQLite DBs.
"""
import argparse,hashlib,importlib.util,json,pathlib,sqlite3,sys,tempfile,time
LIVE=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
MODULE=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/rg_telegram_nas_delivery_shadow_outbox_v1.py")
def module(path):
 spec=importlib.util.spec_from_file_location("rg_outbox_for_rehearsal",str(path))
 if spec is None or spec.loader is None:raise RuntimeError("outbox_module_missing")
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def setup(db):
 db.execute("""CREATE TABLE IF NOT EXISTS nas_rehearsal_claims(
 candidate_id TEXT PRIMARY KEY,approval_event_id TEXT NOT NULL,content_sha256 TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('CLAIMED','SIMULATED','UNCERTAIN')),
 claim_owner TEXT NOT NULL,claimed_at INTEGER NOT NULL,finalized_at INTEGER)""")
def claim(db,outbox,cid,owner,now):
 if not isinstance(owner,str) or len(owner)<4 or not isinstance(cid,str) or len(cid)>80:raise ValueError("invalid_claim")
 db.execute("BEGIN IMMEDIATE")
 try:
  options={j["candidate_id"]:j for j in outbox.gather(db,now) if j["status"]=="shadow_staged"}
  expected=options.get(cid)
  row=db.execute("SELECT approval_event_id,content_sha256,status,source_url FROM nas_shadow_delivery_outbox WHERE candidate_id=?",(cid,)).fetchone()
  if expected is None or row is None or row[2]!="shadow_staged" or row[0]!=expected["event_id"] or row[1]!=expected["hash"] or row[3]!=expected["source_url"]:
   outcome="BLOCKED_INELIGIBLE"
  else:
   previous=db.execute("SELECT state FROM nas_rehearsal_claims WHERE candidate_id=?",(cid,)).fetchone()
   if previous:outcome="BLOCKED_ALREADY_CLAIMED_"+previous[0]
   else:
    db.execute("""INSERT INTO nas_rehearsal_claims VALUES(?,?,?,'CLAIMED',?,?,NULL)""",(cid,row[0],row[1],owner,now))
    outcome="CLAIMED_SIMULATION_ONLY"
  db.execute("COMMIT");return outcome
 except Exception:
  db.execute("ROLLBACK");raise
def finish(db,cid,owner,uncertain,now):
 db.execute("BEGIN IMMEDIATE")
 try:
  count=db.execute("""UPDATE nas_rehearsal_claims SET state=?,finalized_at=?
  WHERE candidate_id=? AND claim_owner=? AND state='CLAIMED'""",("UNCERTAIN" if uncertain else "SIMULATED",now,cid,owner)).rowcount
  db.execute("COMMIT");return count==1
 except Exception:
  db.execute("ROLLBACK");raise
def fixture(db,outbox,now):
 db.executescript("""CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created_at INTEGER,state TEXT);
 CREATE TABLE shadow_event_receipts(event_id TEXT PRIMARY KEY,payload_sha256 TEXT NOT NULL,first_seen_at INTEGER NOT NULL);
 CREATE TABLE moderation_projection(candidate_id TEXT PRIMARY KEY,headline TEXT,image_url TEXT,source_url TEXT,
 decision TEXT,review_event_id TEXT,review_at INTEGER,status TEXT);
 CREATE TABLE shadow_publish_intents(candidate_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,status TEXT);""")
 outbox.setup(db)
 cid="cfed12345678";title="Перевірена новина нового дня";img="https://example.org/new-image.jpg";url="https://example.org/new-report"
 eid="nasreview:"+cid+":"+str(now)+":approved"
 def add(id,kind,src,payload):
  raw=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":"))
  digest=hashlib.sha256((kind+"\0"+src+"\0"+raw).encode()).hexdigest()
  db.execute("INSERT INTO events VALUES(?,?,?,?,?)",(id,kind,raw,now,"shadow"))
  db.execute("INSERT INTO shadow_event_receipts VALUES(?,?,?)",(id,digest,now))
 add("nasnews:v2:"+cid,"news_candidate","nas-local-spool",{"candidate_id":cid,"headline":title,"image_url":img,"source_url":url,"detected_at":now-100})
 add(eid,"moderation_decision","nas-operator-review",{"candidate_id":cid,"decision":"approved","reviewed_at":now,"reason_code":"operator_verified"})
 db.execute("INSERT INTO moderation_projection VALUES(?,?,?,?,?,?,?,?)",(cid,title,img,url,"approved",eid,now,"ready_shadow"))
 db.execute("INSERT INTO shadow_publish_intents VALUES(?,?,?)",(cid,eid,"shadow_only"))
 outbox.stage(db,now)
 return cid
def offline_tests(outbox,now=None):
 now=int(time.time()) if now is None else int(now)
 with sqlite3.connect(":memory:",isolation_level=None) as db:
  cid=fixture(db,outbox,now);setup(db)
  assert outbox.report(db)["staged"]==1
  assert claim(db,outbox,cid,"worker-A",now)=="CLAIMED_SIMULATION_ONLY"
  assert claim(db,outbox,cid,"worker-B",now).startswith("BLOCKED_ALREADY_CLAIMED")
  assert finish(db,cid,"worker-A",True,now)
  assert claim(db,outbox,cid,"worker-C",now+1)=="BLOCKED_ALREADY_CLAIMED_UNCERTAIN"
  db.execute("UPDATE moderation_projection SET decision='rejected',status='rejected'")
  db.execute("DELETE FROM shadow_publish_intents")
  outbox.stage(db,now+2)
  assert claim(db,outbox,cid,"worker-D",now+2)=="BLOCKED_INELIGIBLE"
 with sqlite3.connect(":memory:",isolation_level=None) as db:
  cid=fixture(db,outbox,now);setup(db)
  outbox.quarantine_existing(db,now);outbox.stage(db,now)
  assert outbox.report(db)["staged"]==0
  assert claim(db,outbox,cid,"worker-A",now)=="BLOCKED_INELIGIBLE"
 with sqlite3.connect(":memory:",isolation_level=None) as db:
  cid=fixture(db,outbox,now);setup(db)
  assert claim(db,outbox,cid,"worker-A",now+40*3600)=="BLOCKED_INELIGIBLE"
 return {"at_most_once":"PASS","uncertain_never_retried":"PASS","revoked_blocked":"PASS","no_backfill_blocked":"PASS","expired_blocked":"PASS"}
def rehearsal(db_path,outbox):
 with tempfile.TemporaryDirectory(prefix="rg-nas-dispatch-test-") as d:
  copied=pathlib.Path(d)/"snapshot.sqlite3"
  with sqlite3.connect(str(db_path),timeout=10) as original:
   with sqlite3.connect(str(copied),timeout=10) as dest:original.backup(dest)
  with sqlite3.connect(str(copied),isolation_level=None,timeout=8) as db:
   outbox.setup(db);setup(db)
   before=outbox.report(db);claimed=0;now=int(time.time())
   # ALL claims occur in the disposable copy of the real WAL-aware snapshot.
   for job in outbox.gather(db,now):
    if job["status"]=="shadow_staged":
     if claim(db,outbox,job["candidate_id"],"snapshot-worker",now)=="CLAIMED_SIMULATION_ONLY":claimed+=1
   return {"snapshot":"PASS","outbox_staged":before["staged"],"outbox_blocked":before["blocked"],
     "quarantined":before["pre_cutover_quarantined"],"hypothetical_claims_in_copy":claimed,
     "production_db_writes":0,"telegram_sends":0,"cloudflare_calls":0,
     "live_delivery_enabled":False,"cutover_approved":False}
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","rehearse"))
 p.add_argument("--db",default=str(LIVE));p.add_argument("--outbox-module",default=str(MODULE));a=p.parse_args()
 outbox=module(pathlib.Path(a.outbox_module))
 tests=offline_tests(outbox)
 if a.mode=="selftest":
  print(json.dumps({"status":"DISPATCH_SELFTEST_PASS","tests":tests,"telegram_sends":0,"network_calls":0}));return
 live=pathlib.Path(a.db)
 if not live.is_file() or live.is_symlink():raise RuntimeError("database_missing_or_symlink")
 print(json.dumps({"status":"NAS_DISPATCH_REHEARSAL_PASS_SHADOW_ONLY","tests":tests,"snapshot":rehearsal(live,outbox)},ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","reason":type(e).__name__+":"+str(e)[:150],"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
