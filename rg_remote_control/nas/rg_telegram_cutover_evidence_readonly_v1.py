#!/usr/bin/env python3
"""RG Telegram NAS - read-only cross-system delivery evidence report.
Does not infer Cloudflare delivery from moderation decisions.
Cannot authorize sending even if local records appear clean.
No network, token, SQLite writes, Cloudflare calls or Telegram sends.
"""
import argparse,datetime,json,pathlib,sqlite3,sys,urllib.parse
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
MAX_ROWS=250
def parse(raw):
 try:
  v=json.loads(raw)
  return v if isinstance(v,dict) else {}
 except (TypeError,ValueError):return {}
def report(db):
 tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 required={"moderation_projection","nas_shadow_delivery_outbox","events"}
 if not required<=tables:
  return {"schema":"RG_TELEGRAM_CUTOVER_EVIDENCE_V1","status":"BLOCKED",
          "reason":"schema_missing","missing":sorted(required-tables),"telegram_sends":0}
 events={}
 for eid,raw in db.execute("SELECT event_id,payload FROM events WHERE kind='publication_result' ORDER BY rowid DESC LIMIT 10000"):
  d=parse(raw);cid=d.get("candidate_id")
  if isinstance(cid,str) and cid:events.setdefault(cid,[]).append({"event_id":eid,"status":d.get("status"),
    "message_id_recorded":isinstance(d.get("telegram_message_id"),int) and d["telegram_message_id"]>0})
 rows=[]
 for cid,approval_id,digest,url,state,reason in db.execute(
  "SELECT candidate_id,approval_event_id,content_sha256,source_url,status,reason FROM nas_shadow_delivery_outbox ORDER BY staged_at DESC LIMIT ?",(MAX_ROWS,)):
  local=events.get(cid,[])
  rows.append({"candidate_id":cid,"content_hash":digest[:16],"approval_event":approval_id,
    "source_url":url,"outbox_status":state,"outbox_reason":reason,
    "local_publication_result_records":len(local),"local_records_with_message_id":sum(1 for e in local if e["message_id_recorded"]),
    "cloudflare_delivery_verified":False,
    "telegram_channel_history_verified":False,
    "delivery_decision":"BLOCKED_REQUIRES_RECONCILIATION"})
 counts=dict(db.execute("SELECT status,count(*) FROM nas_shadow_delivery_outbox GROUP BY status"))
 return {"schema":"RG_TELEGRAM_CUTOVER_EVIDENCE_V1","status":"BLOCKED_AWAITING_DELIVERY_EVIDENCE",
   "local_shadow_staged":counts.get("shadow_staged",0),"local_shadow_blocked":counts.get("blocked",0),
   "events_publication_result_total":db.execute("SELECT count(*) FROM events WHERE kind='publication_result'").fetchone()[0],
   "moderation_log_not_delivery_proof":True,"cloudflare_delivery_ledger_available":False,
   "bot_api_history_fetch_supported":False,"cloudflare_previous_sender_disabled_verified":False,
   "sole_writer_lease_verified":False,"cutover_approved":False,
   "items":rows,"telegram_sends":0,"cloudflare_calls":0}
def selftest():
 with sqlite3.connect(":memory:") as db:
  db.execute("CREATE TABLE moderation_projection(candidate_id TEXT PRIMARY KEY,status TEXT)")
  db.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT)")
  db.execute("""CREATE TABLE nas_shadow_delivery_outbox(
   candidate_id TEXT PRIMARY KEY,approval_event_id TEXT,content_sha256 TEXT,
   source_url TEXT,status TEXT,reason TEXT,staged_at INTEGER)""")
  db.execute("INSERT INTO moderation_projection VALUES('abcde0123456','ready_shadow')")
  db.execute("INSERT INTO nas_shadow_delivery_outbox VALUES(?,?,?,?,?,?,?)",
             ("abcde0123456","nasreview:abcde0123456:100:approved","d"*64,
              "https://example.org/news","shadow_staged","awaiting_cross_system_reconciliation",100))
  result=report(db)
  assert result["status"]=="BLOCKED_AWAITING_DELIVERY_EVIDENCE"
  assert result["local_shadow_staged"]==1
  assert not result["cutover_approved"]
  assert result["items"][0]["delivery_decision"]=="BLOCKED_REQUIRES_RECONCILIATION"
  db.execute("INSERT INTO events VALUES(?,?,?)",("e1","publication_result",json.dumps({"candidate_id":"abcde0123456","status":"delivered","telegram_message_id":123})))
  result=report(db)
  assert result["items"][0]["local_records_with_message_id"]==1
  assert result["status"]=="BLOCKED_AWAITING_DELIVERY_EVIDENCE"
  assert result["cloudflare_previous_sender_disabled_verified"] is False
 print(json.dumps({"selftest":"PASS","read_only":True,"message_id_does_not_unlock_cutover":"PASS",
                    "cloudflare_ledger_not_assumed":"PASS","no_live_sending":"PASS"}))
def main():
 p=argparse.ArgumentParser()
 p.add_argument("mode",choices=("selftest","audit"))
 p.add_argument("--db",default=str(DB))
 a=p.parse_args()
 if a.mode=="selftest":selftest();return
 path=pathlib.Path(a.db)
 if not path.is_file() or path.is_symlink():raise RuntimeError("database_not_found_or_symlink")
 uri="file:"+urllib.parse.quote(str(path),safe="/")+"?mode=ro"
 with sqlite3.connect(uri,timeout=10,uri=True) as db:
  result=report(db)
 print(json.dumps(result,ensure_ascii=False,indent=2))
 # BLOCKED here is expected, but nonzero exit for automation safety.
 if result["status"]!="PASS":sys.exit(2)
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"ERROR","reason":type(e).__name__,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
