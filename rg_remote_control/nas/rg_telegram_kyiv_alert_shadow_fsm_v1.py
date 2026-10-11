#!/usr/bin/env python3
"""Offline Kyiv alert transition engine for RG Telegram NAS shadow database.
Only consumes a locally supplied JSON provider result. No HTTP or Telegram calls.
"""
import argparse,json,pathlib,sqlite3,time,hashlib,tempfile
DB="/volume1/docker/RG_TELEGRAM_STATE/migration_shadow.sqlite3"
def ingest(db,raw):
    if set(raw)!={"status","observed_at","source"}:raise ValueError("strict_schema")
    if raw["status"] not in ("ALERT","CLEAR"):raise ValueError("invalid_status")
    if not isinstance(raw["observed_at"],int) or raw["observed_at"]<=0:raise ValueError("observed_at")
    if not isinstance(raw["source"],str) or len(raw["source"])>80 or not raw["source"]:raise ValueError("source")
    db.execute("CREATE TABLE IF NOT EXISTS kyiv_alert_shadow_state (source TEXT PRIMARY KEY, status TEXT NOT NULL, observed_at INTEGER NOT NULL)")
    db.execute("BEGIN IMMEDIATE")
    try:
        old=db.execute("SELECT status,observed_at FROM kyiv_alert_shadow_state WHERE source=?",(raw["source"],)).fetchone()
        if old and raw["observed_at"]<=old[1]: result="STALE_IGNORED"
        elif old and old[0]==raw["status"]:
            db.execute("UPDATE kyiv_alert_shadow_state SET observed_at=? WHERE source=?",(raw["observed_at"],raw["source"]))
            result="UNCHANGED"
        else:
            payload=json.dumps({"status":raw["status"],"observed_at":raw["observed_at"]},sort_keys=True)
            eid="kyiv:shadow:"+hashlib.sha256((raw["source"]+":"+str(raw["observed_at"])+":"+raw["status"]).encode()).hexdigest()[:24]
            db.execute("INSERT OR IGNORE INTO events(event_id,kind,payload,created_at,state) VALUES(?,?,?,?,?)",(eid,"kyiv_alert",payload,int(time.time()),"shadow"))
            db.execute("INSERT INTO kyiv_alert_shadow_state(source,status,observed_at) VALUES (?,?,?) ON CONFLICT(source) DO UPDATE SET status=excluded.status,observed_at=excluded.observed_at",(raw["source"],raw["status"],raw["observed_at"]))
            result="SHADOW_TRANSITION"
        db.execute("COMMIT")
        return result
    except Exception:
        db.execute("ROLLBACK");raise
def test():
    with tempfile.TemporaryDirectory() as d:
        with sqlite3.connect(str(pathlib.Path(d)/"t.db"),isolation_level=None) as db:
            db.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created_at INTEGER,state TEXT)")
            a={"status":"ALERT","observed_at":100,"source":"provider-test"}
            assert ingest(db,a)=="SHADOW_TRANSITION"
            assert ingest(db,a)=="STALE_IGNORED"
            assert ingest(db,{**a,"observed_at":101})=="UNCHANGED"
            assert ingest(db,{**a,"status":"CLEAR","observed_at":102})=="SHADOW_TRANSITION"
            assert db.execute("SELECT count(*) FROM events").fetchone()[0]==2
    print(json.dumps({"selftest":"PASS","alert_clear_transitions":"PASS","stale_protection":"PASS","network_calls":0,"sending_enabled":False}))
def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","status","ingest"]);p.add_argument("--db",default=DB);p.add_argument("--input")
    a=p.parse_args()
    if a.mode=="selftest":test();return
    if a.mode=="ingest" and not a.input:raise SystemExit("BLOCKED: input JSON file required")
    if a.mode=="status":
        with sqlite3.connect(a.db) as db:
            present=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kyiv_alert_shadow_state'").fetchone()
            rows=db.execute("SELECT source,status,observed_at FROM kyiv_alert_shadow_state").fetchall() if present else []
        print(json.dumps({"status":"SHADOW_ONLY","states":rows,"network_calls":0}));return
    path=pathlib.Path(a.input)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>2000:raise SystemExit("BLOCKED: invalid file")
    with sqlite3.connect(a.db,isolation_level=None) as db: result=ingest(db,json.loads(path.read_text("utf-8")))
    print(json.dumps({"status":result,"network_calls":0,"publishing_enabled":False}))
if __name__=="__main__":main()
