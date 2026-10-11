#!/usr/bin/env python3
"""Import actual NAS minute-silence watchdog record existence into RG Telegram shadow SQLite.
Does not interpret publication success, and does not send or poll any external API.
"""
import argparse,hashlib,json,pathlib,re,sqlite3,time
ROOT=pathlib.Path("/volume1/docker")
STORE=ROOT/"RG_TELEGRAM_STATE/migration_shadow.sqlite3"
DIR=ROOT/"RG_NAS_STATE"
NAME=re.compile(r"minute-silence-watchdog-result-(\d{4}-\d{2}-\d{2})\.json$")
def collect(directory):
    records=[]
    for p in sorted(directory.glob("minute-silence-watchdog-result-*.json"))[-30:]:
        m=NAME.fullmatch(p.name)
        if not m or p.is_symlink() or not p.is_file() or p.stat().st_size>100000:continue
        # Date from immutable filename; no assertions about successful delivery.
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        records.append({"event_id":"nas:minute-silence:watchdog:"+m.group(1)+":"+digest[:16],
         "kind":"minute_silence","payload":{"date":m.group(1),"status":"watchdog_recorded"},
         "source":"nas-watchdog"})
    return records
def import_records(directory,dbpath):
    import importlib.util
    modulepath=ROOT/"RG_TELEGRAM_STATE/rg_telegram_nas_event_intake_v1.py"
    spec=importlib.util.spec_from_file_location("rg_intake",str(modulepath))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    stats={"stored":0,"duplicate":0}
    with sqlite3.connect(str(dbpath),timeout=10,isolation_level=None) as db:
        module.init(db)
        for record in collect(directory):
            status=module.intake(db,record)
            if status=="SHADOW_STORED":stats["stored"]+=1
            else:stats["duplicate"]+=1
    return stats
def main():
    a=argparse.ArgumentParser()
    a.add_argument("mode",choices=["selftest","audit","import"])
    args=a.parse_args()
    if args.mode=="selftest":
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            folder=pathlib.Path(d)
            p=folder/"minute-silence-watchdog-result-2026-10-11.json"
            p.write_text('{"unknown_status":"no_delivery_claim"}')
            records=collect(folder)
            assert len(records)==1 and records[0]["payload"]["status"]=="watchdog_recorded"
            assert collect(folder)==records
        print(json.dumps({"selftest":"PASS","publication_claims":0,"network_calls":0}))
        return
    records=collect(DIR)
    if args.mode=="audit":
        print(json.dumps({"status":"READY","records_found":len(records),"network_calls":0,"publishing_enabled":False}))
        return
    if not STORE.is_file():raise SystemExit("BLOCKED: SQLite stage one not initialized")
    stats=import_records(DIR,STORE)
    print(json.dumps({"status":"SHADOW_IMPORTED","stats":stats,"network_calls":0,"publishing_enabled":False,"delivery_verified":False}))
if __name__=="__main__":main()
