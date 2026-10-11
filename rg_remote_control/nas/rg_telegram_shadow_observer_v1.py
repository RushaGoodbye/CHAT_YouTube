#!/usr/bin/env python3
"""RG Telegram migration: read-only NAS state sampler -> SQLite shadow events.
Collects only selected sanitized operational status. No cloud requests or Telegram sends.
"""
import argparse,hashlib,json,pathlib,sqlite3,subprocess,time
ROOT=pathlib.Path("/volume1/docker")
DB=ROOT/"RG_TELEGRAM_STATE/migration_shadow.sqlite3"
FILES={
  "deploy":ROOT/"RG_NAS_STATE/last_deploy_status",
  "deploy_stage":ROOT/"RG_NAS_STATE/deploy_stage",
  "scheduler":ROOT/"RG_NAS_STATE/scheduler_last_check_status",
  "watchdog":ROOT/"RG_NAS_STATE/telegram_watchdog_status",
  "telegram_control":ROOT/"RG_NAS_STATE/telegram_control_plane_status"
}
def collect():
    result={}
    for k,p in FILES.items():
        if p.is_file() and not p.is_symlink() and p.stat().st_size<5000:
            value=p.read_text("utf-8",errors="replace").strip()
            if value in ("OK","ERROR","RUNNING","DEFERRED_QUOTA","QUOTA_COOLDOWN","UP_TO_DATE","COMPLETE","UNKNOWN","SYNCED"):
                result[k]=value
    return result
def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["selftest","sample","status"])
    p.add_argument("--db",default=str(DB))
    args=p.parse_args()
    if args.mode=="selftest":
        a={"deploy":"DEFERRED_QUOTA"}
        fingerprint=hashlib.sha256(json.dumps(a,sort_keys=True).encode()).hexdigest()
        assert fingerprint==hashlib.sha256(json.dumps(dict(a),sort_keys=True).encode()).hexdigest()
        print(json.dumps({"selftest":"PASS","external_calls":0,"real_publishing":False}));return
    data=collect()
    if args.mode=="status":
        print(json.dumps({"status":"READ_ONLY","sample":data,"external_calls":0}));return
    if not data:
        print(json.dumps({"status":"NO_SAFE_STATE_FOUND","written":0}));return
    conn=sqlite3.connect(args.db,timeout=10)
    payload=json.dumps(data,sort_keys=True)
    fingerprint=hashlib.sha256(payload.encode()).hexdigest()
    event_id="nas:operational:"+fingerprint
    now=int(time.time())
    with conn:
        conn.execute("INSERT OR IGNORE INTO events(event_id,kind,payload,created_at,state) VALUES(?,?,?,?,?)",(event_id,"nas_operational",payload,now,"shadow"))
    print(json.dumps({"status":"SHADOW_SAMPLED","event_id":event_id,"states":len(data),"external_calls":0,"publishing_enabled":False}))
if __name__=="__main__":main()
