#!/usr/bin/env python3
"""Explicit local operator moderation into NAS event log, shadow only.
Never reads Telegram updates or publishes. No automatic approval.
"""
import argparse,importlib.util,json,pathlib,re,sqlite3,sys,tempfile,time,urllib.parse
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
MAX_AGE=36*3600
def load_intake():
 path=pathlib.Path(__file__).with_name("rg_telegram_nas_event_intake_v1.py")
 if not path.is_file():raise ValueError("intake_not_installed")
 spec=importlib.util.spec_from_file_location("rg_event_intake",str(path))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module
def check_https(uri):
 if not isinstance(uri,str) or len(uri)>1800:return False
 try:
  u=urllib.parse.urlsplit(uri)
  return u.scheme=="https" and bool(u.hostname) and not u.username and not u.password and not u.fragment and u.port in (None,443)
 except ValueError:return False
def last_news_age(db,cid,now):
 rows=db.execute("SELECT payload FROM events WHERE kind='news_candidate' ORDER BY rowid DESC LIMIT 5000")
 for (raw,) in rows:
  try:
   obj=json.loads(raw)
   if obj.get("candidate_id")!=cid:continue
   published=obj.get("detected_at")
   if isinstance(published,int) and not isinstance(published,bool) and now-MAX_AGE<=published<=now+300:
    return True
  except (ValueError,TypeError):continue
 return False
def submit(db_path,cid,decision,confirmed=False,now=None):
 if not confirmed:raise ValueError("human_confirmation_required")
 if not re.fullmatch(r"[0-9a-f]{12}",cid):raise ValueError("invalid_candidate_id")
 if decision not in ("approved","rejected","deferred"):raise ValueError("invalid_decision")
 now=int(time.time()) if now is None else int(now)
 if db_path.is_symlink() or not db_path.is_file():raise ValueError("database_missing")
 mod=load_intake()
 with sqlite3.connect(str(db_path),timeout=10,isolation_level=None) as db:
  mod.init(db)
  if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='moderation_projection'").fetchone():
   raise ValueError("moderation_projection_missing")
  row=db.execute("SELECT headline,image_url,source_url,status,review_at FROM moderation_projection WHERE candidate_id=?",(cid,)).fetchone()
  if row is None:raise ValueError("candidate_not_found")
  headline,image,source,status,last_review_at=row
  # A second action in the same wall-clock second must override the first.
  # Keep the per-candidate review timestamp strictly increasing.
  if last_review_at is not None and int(last_review_at)>=now:now=int(last_review_at)+1
  if decision=="approved":
   if not headline or not check_https(image) or not check_https(source):raise ValueError("incomplete_news")
   if not last_news_age(db,cid,now):raise ValueError("stale_or_undated_news")
  event={"event_id":"nasreview:"+cid+":"+str(now)+":"+decision,
   "kind":"moderation_decision","source":"nas-operator-review",
   "payload":{"candidate_id":cid,"decision":decision,"reviewed_at":now,"reason_code":"operator_verified"}}
  outcome=mod.intake(db,event)
 return {"status":outcome,"candidate_id":cid,"decision":decision,"shadow_only":True,"telegram_sends":0}
def selftest():
 mod=load_intake()
 with tempfile.TemporaryDirectory() as tmp:
  dbp=pathlib.Path(tmp)/"test.db"
  with sqlite3.connect(str(dbp),isolation_level=None) as db:
   db.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created_at INTEGER,state TEXT)")
   db.execute("CREATE TABLE moderation_projection(candidate_id TEXT PRIMARY KEY,headline TEXT,image_url TEXT,source_url TEXT,status TEXT)")
   mod.init(db)
   cid="aabbccddeeff"
   db.execute("INSERT INTO moderation_projection VALUES(?,?,?,?,?)",(cid,"Latest verified report","https://example.org/image.jpg","https://example.org/news","awaiting_review"))
   mod.intake(db,{"event_id":"nasnews:v2:"+cid,"kind":"news_candidate","source":"nas-local-spool",
      "payload":{"candidate_id":cid,"headline":"Latest verified report","source_url":"https://example.org/news","image_url":"https://example.org/image.jpg","detected_at":1000}})
  try:submit(dbp,cid,"approved",now=1050)
  except ValueError:pass
  else:raise AssertionError("approved_without_confirmation")
  good=submit(dbp,cid,"approved",confirmed=True,now=1050)
  assert good["status"]=="SHADOW_STORED"
  assert submit(dbp,cid,"approved",confirmed=True,now=1050)["status"]=="DUPLICATE"
  try:submit(dbp,cid,"approved",confirmed=True,now=1000+MAX_AGE+1)
  except ValueError as e:assert str(e)=="stale_or_undated_news"
  else:raise AssertionError("stale_approved")
  revoked=submit(dbp,cid,"rejected",confirmed=True,now=1050)
  assert revoked["status"]=="SHADOW_STORED"
  with sqlite3.connect(str(dbp)) as db:
   items=[json.loads(x[0]) for x in db.execute("SELECT payload FROM events WHERE kind='moderation_decision' ORDER BY rowid").fetchall()]
   assert len(items)==2 and items[-1]["reviewed_at"]==1051
  assert submit(dbp,cid,"deferred",confirmed=True,now=1000+MAX_AGE+1)["status"]=="SHADOW_STORED"
  with sqlite3.connect(str(dbp)) as db:
   assert db.execute("SELECT count(*) FROM events WHERE kind='moderation_decision'").fetchone()[0]==3
 print(json.dumps({"selftest":"PASS","human_confirmation":"PASS","freshness_gate":"PASS","dedup":"PASS","rejection_allowed":"PASS","same_second_revocation":"PASS","telegram_sends":0}))
def main():
 p=argparse.ArgumentParser()
 p.add_argument("mode",choices=["selftest","record","status"])
 p.add_argument("--db",default=str(DB))
 p.add_argument("--candidate-id")
 p.add_argument("--decision",choices=["approved","rejected","deferred"])
 p.add_argument("--confirm-operator-review",action="store_true")
 a=p.parse_args()
 if a.mode=="selftest":selftest();return
 if a.mode=="status":
  with sqlite3.connect("file:"+str(a.db)+"?mode=ro",uri=True) as db:
   groups=dict(db.execute("SELECT status,count(*) FROM moderation_projection GROUP BY status"))
  print(json.dumps({"status":"LOCAL_REVIEW_READY","candidate_states":groups,"send_enabled":False},ensure_ascii=False));return
 if not a.candidate_id or not a.decision:raise ValueError("missing_candidate_or_decision")
 print(json.dumps(submit(pathlib.Path(a.db),a.candidate_id,a.decision,a.confirm_operator_review),ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","reason":type(e).__name__+":"+str(e)[:65],"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
