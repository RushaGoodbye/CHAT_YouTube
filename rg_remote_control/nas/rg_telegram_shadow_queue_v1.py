#!/usr/bin/env python3
"""RG Telegram migration: shadow-only recoverable delivery queue.
Never makes network calls or publishes Telegram messages.
"""
import argparse,json,pathlib,sqlite3,tempfile,time,uuid
DB_DEFAULT="/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3"
def connect(path):
    db=sqlite3.connect(path,timeout=8,isolation_level=None)
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS shadow_queue (
       job_id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,
       status TEXT NOT NULL DEFAULT 'waiting',attempts INTEGER NOT NULL DEFAULT 0,
       lease_until INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,
       updated_at INTEGER NOT NULL,
       CHECK(status IN ('waiting','leased','shadow_done','shadow_failed'))
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_shadow_queue_ready ON shadow_queue(status,lease_until)")
    return db
def enqueue(db,id,kind,payload):
    n=int(time.time())
    db.execute("INSERT OR IGNORE INTO shadow_queue(job_id,kind,payload,created_at,updated_at) VALUES (?,?,?,?,?)",(id,kind,json.dumps(payload,ensure_ascii=False,sort_keys=True),n,n))
def claim(db,lease=30):
    now=int(time.time())
    db.execute("BEGIN IMMEDIATE")
    try:
        item=db.execute("SELECT job_id,kind FROM shadow_queue WHERE status='waiting' OR (status='leased' AND lease_until<=?) ORDER BY created_at,job_id LIMIT 1",(now,)).fetchone()
        if item:
            db.execute("UPDATE shadow_queue SET status='leased',attempts=attempts+1,lease_until=?,updated_at=? WHERE job_id=?",(now+lease,now,item[0]))
        db.execute("COMMIT")
        return item
    except:
        db.execute("ROLLBACK")
        raise
def finish(db,id):
    db.execute("UPDATE shadow_queue SET status='shadow_done',lease_until=0,updated_at=? WHERE job_id=? AND status='leased'",(int(time.time()),id))
def selftest():
    with tempfile.TemporaryDirectory() as d:
        with connect(str(pathlib.Path(d)/"q.db")) as db:
            enqueue(db,"test:1","test",{"x":1})
            enqueue(db,"test:1","test",{"x":1})
            assert db.execute("SELECT count(*) FROM shadow_queue").fetchone()[0]==1
            a=claim(db)
            assert a[0]=="test:1" and claim(db) is None
            db.execute("UPDATE shadow_queue SET lease_until=0 WHERE job_id='test:1'")
            assert claim(db)[0]=="test:1"
            finish(db,"test:1")
            assert claim(db) is None
    print(json.dumps({"selftest":"PASS","dedupe":"PASS","lease_recovery":"PASS","shadow_only":True,"external_calls":0}))
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["selftest","initialize","status"])
    parser.add_argument("--db",default=DB_DEFAULT)
    args=parser.parse_args()
    if args.mode=="selftest":selftest();return
    path=pathlib.Path(args.db)
    if args.mode=="status" and not path.exists():
        print(json.dumps({"status":"NOT_INITIALIZED"}));return
    path.parent.mkdir(parents=True,exist_ok=True)
    with connect(str(path)) as db:
        counts=dict(db.execute("SELECT status,count(*) FROM shadow_queue GROUP BY status").fetchall())
        integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
    print(json.dumps({"status":"SHADOW_QUEUE_READY","mode":args.mode,"counts":counts,"integrity":integrity,"sending_enabled":False}))
if __name__=="__main__":main()
