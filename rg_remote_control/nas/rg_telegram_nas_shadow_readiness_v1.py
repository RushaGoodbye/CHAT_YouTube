#!/usr/bin/env python3
"""RG Telegram NAS: read-only shadow publication readiness audit.
Checks SQLite human-review provenance, current status, image and date.
No Telegram API, no Cloudflare, no production database writes.
"""
import argparse,json,pathlib,sqlite3,sys,tempfile,time,urllib.parse
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
MAX_AGE=36*3600
def valid_url(url):
 if not isinstance(url,str) or len(url)>1800:return False
 try:
  u=urllib.parse.urlsplit(url)
  return u.scheme=="https" and bool(u.hostname) and not u.username and not u.password and not u.fragment and u.port in (None,443)
 except ValueError:return False
def decode(raw):
 try:
  v=json.loads(raw)
  return v if isinstance(v,dict) else {}
 except (ValueError,TypeError):return {}
def audit(db,now=None):
 now=int(time.time()) if now is None else int(now)
 tabs={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 required={"events","moderation_projection","shadow_publish_intents"}
 if not required<=tabs:return {"status":"BLOCKED","reason":"missing_tables","missing":sorted(required-tabs),"telegram_sends":0}
 integrity=db.execute("PRAGMA quick_check(1)").fetchone()[0]
 states=dict(db.execute("SELECT status,count(*) FROM moderation_projection GROUP BY status"))
 news={};reviews={}
 for eid,kind,raw in db.execute("SELECT event_id,kind,payload FROM events WHERE kind IN ('news_candidate','moderation_decision') ORDER BY rowid DESC"):
  doc=decode(raw)
  if kind=="news_candidate":
   cid=doc.get("candidate_id")
   if isinstance(cid,str):news.setdefault(cid,[]).append(doc)
  else:reviews[eid]=doc
 rows=db.execute("SELECT candidate_id,headline,image_url,source_url,decision,status,review_event_id,review_at FROM moderation_projection").fetchall()
 intents=db.execute("SELECT candidate_id,event_id,status FROM shadow_publish_intents").fetchall()
 lookup={x[0]:(x[1],x[2]) for x in intents}
 problems=[];valid=0;expired=0;approved_urls=[]
 if integrity!="ok":problems.append("sqlite_integrity")
 for cid,title,img,url,decision,status,review_eid,review_at in rows:
  intent=lookup.get(cid)
  if status!="ready_shadow":
   if intent:problems.append("unapproved_intent")
   continue
  approved_urls.append(url)
  if decision!="approved" or intent is None:
   problems.append("missing_operator_approval_or_intent");continue
  eid,mode=intent
  if mode!="shadow_only" or eid!=review_eid or not eid.startswith("nasreview:"+cid+":"):
   problems.append("intent_review_mismatch");continue
  review=reviews.get(eid)
  if not review or review.get("candidate_id")!=cid or review.get("decision")!="approved" or review.get("reviewed_at")!=review_at:
   problems.append("approval_record_mismatch");continue
  if not isinstance(title,str) or not title.strip() or not valid_url(url) or not valid_url(img):
   problems.append("missing_text_or_photo");continue
  matches=[n for n in news.get(cid,[]) if n.get("headline")==title and n.get("source_url")==url and n.get("image_url")==img]
  if not matches:
   problems.append("source_record_mismatch");continue
  if not any(isinstance(n.get("detected_at"),int) and not isinstance(n["detected_at"],bool) and now-MAX_AGE<=n["detected_at"]<=now+300 for n in matches):
   expired+=1;problems.append("approved_item_expired");continue
  valid+=1
 known={r[0] for r in rows}
 if any(cid not in known for cid in lookup):problems.append("orphan_intent")
 if len(intents)!=len(lookup):problems.append("duplicate_intent")
 if len(approved_urls)!=len(set(approved_urls)):problems.append("duplicate_approved_source_url")
 return {"schema":"RG_TELEGRAM_NAS_SHADOW_READINESS_V1",
         "status":"PASS_SHADOW_ONLY" if not problems else "BLOCKED",
         "database_integrity":integrity,
         "moderation_states":states,
         "shadow_intents":len(intents),
         "valid_approved_intents":valid,
         "approved_expired":expired,
         "issues":sorted(set(problems)),
         "live_delivery_verified":False,
         "cross_system_duplicate_safety_verified":False,
         "ready_for_live_cutover":False,
         "telegram_sends":0,"cloudflare_calls":0}
def selftest():
 now=1760212800
 with tempfile.TemporaryDirectory() as d:
  with sqlite3.connect(str(pathlib.Path(d)/"case.sqlite3"),isolation_level=None) as db:
   db.executescript("""CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT);
CREATE TABLE moderation_projection(candidate_id TEXT PRIMARY KEY,headline TEXT,image_url TEXT,source_url TEXT,decision TEXT,status TEXT,review_event_id TEXT,review_at INTEGER);
CREATE TABLE shadow_publish_intents(candidate_id TEXT PRIMARY KEY,event_id TEXT,status TEXT);""")
   cid="e14a68edca9d";title="Підтверджена новина про події Харкова"
   url="https://example.org/article";img="https://example.org/photo.jpg";eid="nasreview:"+cid+":"+str(now)+":approved"
   news={"candidate_id":cid,"headline":title,"source_url":url,"image_url":img,"detected_at":now-300}
   decision={"candidate_id":cid,"decision":"approved","reviewed_at":now}
   db.execute("INSERT INTO events VALUES(?,?,?)",("nasnews:v2:"+cid,"news_candidate",json.dumps(news)))
   db.execute("INSERT INTO events VALUES(?,?,?)",(eid,"moderation_decision",json.dumps(decision)))
   db.execute("INSERT INTO moderation_projection VALUES(?,?,?,?,?,?,?,?)",(cid,title,img,url,"approved","ready_shadow",eid,now))
   db.execute("INSERT INTO shadow_publish_intents VALUES(?,?,?)",(cid,eid,"shadow_only"))
   assert audit(db,now)["status"]=="PASS_SHADOW_ONLY"
   assert audit(db,now)["valid_approved_intents"]==1
   assert audit(db,now)["ready_for_live_cutover"] is False
   db.execute("UPDATE moderation_projection SET decision='rejected',status='rejected'")
   assert "unapproved_intent" in audit(db,now)["issues"]
   db.execute("UPDATE moderation_projection SET decision='approved',status='ready_shadow'")
   assert "approved_item_expired" in audit(db,now+MAX_AGE+3600)["issues"]
   db.execute("DELETE FROM shadow_publish_intents")
   assert "missing_operator_approval_or_intent" in audit(db,now)["issues"]
 print(json.dumps({"selftest":"PASS","approval_chain":"PASS","revocation_guard":"PASS","expiration_guard":"PASS","missing_intent_guard":"PASS","telegram_sends":0,"network_calls":0}))
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","audit"]);p.add_argument("--db",default=str(DB));a=p.parse_args()
 if a.mode=="selftest":selftest();return
 path=pathlib.Path(a.db)
 if not path.is_file() or path.is_symlink():raise ValueError("database_missing_or_symlink")
 url="file:"+urllib.parse.quote(str(path),safe="/")+"?mode=ro"
 with sqlite3.connect(url,uri=True,timeout=8) as db:result=audit(db)
 print(json.dumps(result,ensure_ascii=False))
 if result["status"]=="BLOCKED":sys.exit(1)
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","error_class":type(e).__name__,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
