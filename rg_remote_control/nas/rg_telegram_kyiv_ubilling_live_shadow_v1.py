#!/usr/bin/env python3
"""RG NAS Kyiv alert live shadow poll. Ubilling public API; no Telegram sends.
Run every 60 seconds; fail closed for ambiguous Kyiv city identity.
"""
import argparse, importlib.util, json, pathlib, sqlite3, sys, time, urllib.request
API="https://ubilling.net.ua/aerialalerts/"
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE")
def get_state(data):
    states=data.get("states") if isinstance(data,dict) else None
    if not isinstance(states,dict): raise ValueError("states_missing")
    city_keys=["м. Київ","м.Київ","місто Київ","Київ","Kyiv City","Kyiv"]
    hits=[(k,states[k]) for k in city_keys if k in states]
    if len(hits)!=1:raise ValueError("Kyiv city missing or ambiguous; refusing to infer from oblast")
    city=hits[0][1]
    if not isinstance(city,dict) or type(city.get("alertnow")) is not bool:raise ValueError("Kyiv alertnow not boolean")
    return "ALERT" if city["alertnow"] else "CLEAR"
def fetch():
    req=urllib.request.Request(API,headers={"User-Agent":"RG-Telegram-NAS-shadow/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=12) as resp:
        if resp.status!=200: raise ValueError("HTTP "+str(resp.status))
        raw=resp.read(350001)
    if len(raw)>350000:raise ValueError("response too large")
    return json.loads(raw)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["selftest","probe","once","status"])
    a=p.parse_args()
    if a.mode=="selftest":
        assert get_state({"states":{"м. Київ":{"alertnow":True},"Київська область":{"alertnow":False}}})=="ALERT"
        assert get_state({"states":{"м. Київ":{"alertnow":False}}})=="CLEAR"
        try:get_state({"states":{"Київська область":{"alertnow":True}}});raise AssertionError("obscure area")
        except ValueError:pass
        print(json.dumps({"selftest":"PASS","city_oblast_separation":"PASS","sending_enabled":False}));return
    if a.mode=="status":
        db=ROOT/"migration_shadow.sqlite3"
        if not db.is_file():raise ValueError("database missing")
        with sqlite3.connect(str(db)) as conn:
            existing=conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kyiv_alert_shadow_state'").fetchone()
            rows=conn.execute("SELECT source,status,observed_at FROM kyiv_alert_shadow_state").fetchall() if existing else []
        print(json.dumps({"status":"SHADOW_STATUS","states":rows,"sending_enabled":False}));return
    data=fetch()
    status=get_state(data)
    if a.mode=="probe":
        print(json.dumps({"status":"PROVIDER_OK","kyiv_state":status,"source":"ubilling","sending_enabled":False}));return
    module=ROOT/"rg_telegram_kyiv_alert_shadow_fsm_v1.py"
    spec=importlib.util.spec_from_file_location("rg_alert_fsm",str(module))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    with sqlite3.connect(str(ROOT/"migration_shadow.sqlite3"),timeout=10,isolation_level=None) as db:
        outcome=mod.ingest(db,{"source":"ubilling:kyiv-city","status":status,"observed_at":int(time.time())})
    print(json.dumps({"status":"SHADOW_POLL_OK","kyiv_state":status,"transition":outcome,"sending_enabled":False}))
if __name__=="__main__":
    try:main()
    except Exception as e:
        print(json.dumps({"status":"BLOCKED","error":str(e)[:180],"sending_enabled":False}),file=sys.stderr)
        sys.exit(1)
