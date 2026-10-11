#!/usr/bin/env python3
"""RG Telegram NAS shadow event intake. Local stdin JSON only; NO delivery.
Input v1: {"event_id":"...","kind":"news_candidate|moderation_decision|kyiv_alert|minute_silence|publication_result","payload":{...},"source":"..."}
"""
import argparse, hashlib, json, pathlib, sqlite3, sys, tempfile, time
DEFAULT="/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3"
KINDS={"news_candidate","moderation_decision","kyiv_alert","minute_silence","publication_result"}
ALLOWED={"news_candidate":{"headline","source_url","image_url","detected_at","candidate_id"},
"moderation_decision":{"candidate_id","decision","reviewed_at","reason_code"},
"kyiv_alert":{"status","observed_at","provider_event_id"},
"minute_silence":{"date","status","observed_at"},
"publication_result":{"candidate_id","status","telegram_message_id","recorded_at"}}
def validate(obj):
    if not isinstance(obj,dict) or set(obj)!={"event_id","kind","payload","source"}:raise ValueError("schema_fields")
    eid=obj["event_id"]
    if not isinstance(eid,str) or not 4<=len(eid)<=180 or any(x not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:._-" for x in eid):raise ValueError("event_id")
    kind=obj["kind"];payload=obj["payload"];src=obj["source"]
    if kind not in KINDS or not isinstance(payload,dict) or not payload or set(payload)-ALLOWED[kind]:raise ValueError("payload_schema")
    if not isinstance(src,str) or not 2<=len(src)<=80 or any(x not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:._-" for x in src):raise ValueError("source")
    for key,value in payload.items():
        if value is not None and not isinstance(value,(str,int,bool)):raise ValueError("payload_type")
        if isinstance(value,str) and len(value)>3000:raise ValueError("payload_length")
    if kind=="news_candidate" and not payload.get("image_url"):raise ValueError("news_image_required")
    if kind=="moderation_decision" and payload.get("decision") not in ("approved","rejected","deferred"):raise ValueError("decision")
    if kind=="kyiv_alert" and payload.get("status") not in ("ALERT","CLEAR"):raise ValueError("alert_status")
    return obj
def init(db):
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS shadow_event_receipts (event_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL, first_seen_at INTEGER NOT NULL)""")
    # Requires the stage 1 database schema.
    columns={row[1] for row in db.execute("PRAGMA table_info(events)")}
    if not {"event_id","kind","payload","created_at","state"} <= columns:raise ValueError("stage1_events_schema_missing")
def intake(db,obj):
    obj=validate(obj)
    payload=json.dumps(obj["payload"],sort_keys=True,ensure_ascii=False,separators=(",",":"))
    digest=hashlib.sha256((obj["kind"]+"\0"+obj["source"]+"\0"+payload).encode()).hexdigest()
    now=int(time.time())
    db.execute("BEGIN IMMEDIATE")
    try:
        old=db.execute("SELECT payload_sha256 FROM shadow_event_receipts WHERE event_id=?",(obj["event_id"],)).fetchone()
        if old:
            if old[0]!=digest:raise ValueError("event_id_conflict")
            result="DUPLICATE"
        else:
            db.execute("INSERT INTO shadow_event_receipts VALUES(?,?,?)",(obj["event_id"],digest,now))
            db.execute("INSERT INTO events(event_id,kind,payload,created_at,state) VALUES (?,?,?,?,?)",(obj["event_id"],obj["kind"],payload,now,"shadow"))
            result="SHADOW_STORED"
        db.execute("COMMIT")
        return result
    except Exception:
        db.execute("ROLLBACK");raise
def selftest():
    with tempfile.TemporaryDirectory() as d:
        with sqlite3.connect(str(pathlib.Path(d)/"test.db"),isolation_level=None) as db:
            db.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created_at INTEGER,state TEXT)")
            init(db)
            a={"event_id":"alert:20261011:123","kind":"kyiv_alert","source":"nas-test","payload":{"status":"ALERT","provider_event_id":"123"}}
            assert intake(db,a)=="SHADOW_STORED"
            assert intake(db,a)=="DUPLICATE"
            try:
                intake(db,{**a,"payload":{"status":"CLEAR"}})
                raise AssertionError("conflict accepted")
            except ValueError:pass
            assert db.execute("SELECT count(*) FROM events").fetchone()[0]==1
    print(json.dumps({"selftest":"PASS","event_validation":"PASS","dedup":"PASS","conflict_detection":"PASS","network_calls":0,"publishing_enabled":False}))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["selftest","initialize","status","ingest"])
    p.add_argument("--db",default=DEFAULT)
    args=p.parse_args()
    if args.mode=="selftest":selftest();return
    path=pathlib.Path(args.db)
    if not path.is_file() or path.is_symlink():raise SystemExit("BLOCKED: stage1 database missing")
    with sqlite3.connect(str(path),timeout=10,isolation_level=None) as db:
        init(db)
        if args.mode=="ingest":
            raw=sys.stdin.read(16000)
            if len(raw)>=16000:raise SystemExit("BLOCKED: oversized event")
            outcome=intake(db,json.loads(raw))
            print(json.dumps({"status":outcome,"publishing_enabled":False,"network_calls":0}))
        else:
            count=db.execute("SELECT count(*) FROM shadow_event_receipts").fetchone()[0]
            print(json.dumps({"status":"INTAKE_READY","mode":args.mode,"receipts":count,"publishing_enabled":False,"network_calls":0}))
if __name__=="__main__":
    try:main()
    except (ValueError,sqlite3.Error,json.JSONDecodeError) as e:raise SystemExit("BLOCKED: "+str(e)[:150])
