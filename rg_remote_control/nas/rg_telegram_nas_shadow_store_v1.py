#!/usr/bin/env python3
"""RG Telegram NAS Migration stage 1: local shadow state store. No live writes."""
import argparse, json, pathlib, sqlite3, tempfile, time
SCHEMA="""
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
 created_at INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'shadow',
 CHECK(state IN ('shadow','queued','processing','delivered','failed'))
);
CREATE TABLE IF NOT EXISTS delivery_ledger (
 idempotency_key TEXT PRIMARY KEY, event_id TEXT NOT NULL,
 target TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 attempt_count INTEGER NOT NULL DEFAULT 0, telegram_message_id INTEGER,
 updated_at INTEGER NOT NULL,
 CHECK(state IN ('pending','inflight','confirmed','failed','uncertain'))
);
CREATE TABLE IF NOT EXISTS checkpoints (
 component TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_state ON delivery_ledger(state,updated_at);
"""
def connect(p):
    db=sqlite3.connect(p)
    db.executescript(SCHEMA)
    return db
def shadow_record(db, event_id, kind, payload, target):
    now=int(time.time())
    serialized=json.dumps(payload,sort_keys=True,ensure_ascii=False)
    with db:
        db.execute("INSERT OR IGNORE INTO events(event_id,kind,payload,created_at) VALUES (?,?,?,?)",(event_id,kind,serialized,now))
        db.execute("INSERT OR IGNORE INTO delivery_ledger(idempotency_key,event_id,target,updated_at) VALUES (?,?,?,?)",(event_id+":"+target,event_id,target,now))
def selftest():
    with tempfile.TemporaryDirectory() as d:
        p=pathlib.Path(d)/"shadow.db"
        with connect(p) as db:
            shadow_record(db,"alert:test:1","kyiv_alert",{"active":True},"test:channel")
            shadow_record(db,"alert:test:1","kyiv_alert",{"active":True},"test:channel")
            assert db.execute("SELECT count(*) FROM events").fetchone()[0]==1
            assert db.execute("SELECT count(*) FROM delivery_ledger").fetchone()[0]==1
            assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        print(json.dumps({"selftest":"PASS","deduplication":"PASS","sqlite_integrity":"PASS","telegram_calls":0,"cloudflare_calls":0}))
def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["selftest","initialize","status"])
    p.add_argument("--db",default="/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3")
    a=p.parse_args()
    if a.mode=="selftest":selftest();return
    path=pathlib.Path(a.db)
    if a.mode=="status" and not path.exists():
        print(json.dumps({"status":"NOT_INITIALIZED"}));return
    path.parent.mkdir(parents=True,exist_ok=True)
    with connect(path) as db:
        integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
        counts={t:db.execute("SELECT count(*) FROM "+t).fetchone()[0] for t in ("events","delivery_ledger","checkpoints")}
    print(json.dumps({"status":"SHADOW_READY","mode":a.mode,"database":str(path),"integrity":integrity,"counts":counts,"publishing_enabled":False,"external_calls":0}))
if __name__=="__main__":main()
