#!/usr/bin/env python3
"""File-to-SQLite Telegram shadow bridge. No network, no Telegram sends."""
import argparse, importlib.util, json, os, pathlib, sqlite3, tempfile
DEFAULT_ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE")
def load_intake(path):
    spec=importlib.util.spec_from_file_location("rg_intake",path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def run(root,intake_path,limit):
    incoming=root/"incoming";done=root/"processed";bad=root/"rejected"
    for folder in (incoming,done,bad):folder.mkdir(parents=True,exist_ok=True)
    intake=load_intake(intake_path)
    db=sqlite3.connect(str(root/"migration_shadow.sqlite3"),timeout=10,isolation_level=None)
    intake.init(db)
    stats={"stored":0,"duplicates":0,"rejected":0,"left":0}
    for path in sorted(incoming.glob("*.json"))[:limit]:
        if path.is_symlink() or not path.is_file():continue
        if path.stat().st_size>16000:
            result="REJECTED"
        else:
            try:
                item=json.loads(path.read_text("utf-8"))
                result=intake.intake(db,item)
            except (ValueError,sqlite3.Error,UnicodeError,json.JSONDecodeError):
                result="REJECTED"
        destination=(bad if result=="REJECTED" else done)/path.name
        if destination.exists():
            # Never overwrite or drop records with colliding file names.
            stats["left"]+=1;continue
        os.replace(path,destination)
        if result=="SHADOW_STORED":stats["stored"]+=1
        elif result=="DUPLICATE":stats["duplicates"]+=1
        else:stats["rejected"]+=1
    db.close()
    return stats
def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        with sqlite3.connect(str(root/"migration_shadow.sqlite3")) as db:
            db.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created_at INTEGER,state TEXT)")
        src=root/"incoming";src.mkdir()
        v={"event_id":"kyiv:sample:1","kind":"kyiv_alert","payload":{"status":"ALERT","provider_event_id":"sample:1"},"source":"nas-shadow"}
        (src/"event1.json").write_text(json.dumps(v),"utf-8")
        (src/"event2.json").write_text(json.dumps(v),"utf-8")
        (src/"bad.json").write_text("{not-json","utf-8")
        a=run(root,pathlib.Path(__file__).parent/"rg_telegram_nas_event_intake_v1.py",20)
        assert a=={"stored":1,"duplicates":1,"rejected":1,"left":0},a
    print(json.dumps({"selftest":"PASS","stored":1,"dedupe":1,"rejected":1,"network_calls":0,"publishing_enabled":False}))
def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","initialize","once","status"])
    p.add_argument("--root",default=str(DEFAULT_ROOT));p.add_argument("--intake",default=str(DEFAULT_ROOT/"rg_telegram_nas_event_intake_v1.py"))
    a=p.parse_args();root=pathlib.Path(a.root)
    if a.mode=="selftest":selftest();return
    if a.mode=="initialize":
        for x in ("incoming","processed","rejected"):(root/x).mkdir(parents=True,exist_ok=True)
        print(json.dumps({"status":"BRIDGE_READY","publishing_enabled":False}));return
    if a.mode=="status":
        print(json.dumps({"status":"SHADOW_BRIDGE_STATUS","incoming":len(list((root/"incoming").glob("*.json"))) if (root/"incoming").is_dir() else 0,"publishing_enabled":False}));return
    print(json.dumps({"status":"SHADOW_BRIDGE_RUN","result":run(root,pathlib.Path(a.intake),100),"publishing_enabled":False}))
if __name__=="__main__":main()
