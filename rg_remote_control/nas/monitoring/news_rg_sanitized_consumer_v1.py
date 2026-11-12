#!/usr/bin/env python3
"""Read and validate only RG Telegram's non-secret NAS diagnostic export.

No private storage access, Telegram calls, or state changes. Missing or stale
export is an explicit UNKNOWN, never a healthy status.
"""
import argparse
import json
import os
import pathlib
import re
import stat
import time

SCHEMA="RG_NEWS_NAS_SANITIZED_EXPORT_V1"
EXPECTED_LABELS={
    "operator","review_staging","private_receipts",
    "editorial_decisions","watermark_handoff",
}
class HealthError(ValueError):pass

def evaluate(doc, now=None, max_age=1200):
    if not isinstance(doc,dict) or set(doc)!={
        "schema","generated_at_unix","contains_secrets","private_messages_read",
        "telegram_api_calls","publications","source","locations"}:
        raise HealthError("INVALID_SCHEMA")
    if doc["schema"]!=SCHEMA or doc["source"]!="LOCAL_NAS_METADATA_ONLY":
        raise HealthError("SOURCE_MISMATCH")
    if doc["contains_secrets"] is not False or doc["private_messages_read"] != 0 or doc["telegram_api_calls"] != 0 or doc["publications"] != 0:
        raise HealthError("UNSAFE_EXPORT")
    timestamp=doc["generated_at_unix"]
    if type(timestamp) is not int or timestamp<=0:
        raise HealthError("INVALID_TIMESTAMP")
    now=int(time.time() if now is None else now)
    age=now-timestamp
    if age < -60:raise HealthError("CLOCK_IN_FUTURE")
    loc=doc["locations"]
    if not isinstance(loc,dict) or set(loc)!=EXPECTED_LABELS:
        raise HealthError("INVALID_LOCATIONS")
    for label,entry in loc.items():
        if not isinstance(entry,dict) or set(entry) not in ({"exists"},{"exists","directory"},{"exists","stat_error"}):
            raise HealthError("INVALID_LOCATION_RECORD")
        if type(entry.get("exists")) is not bool:
            raise HealthError("INVALID_LOCATION_EXISTENCE")
        if entry.get("directory") is True and entry["exists"] is not True:
            raise HealthError("INVALID_LOCATION_TYPE")
        if "directory" in entry and entry["directory"] is not True:
            raise HealthError("INVALID_LOCATION_TYPE")
        if "stat_error" in entry and entry["stat_error"] is not True:
            raise HealthError("INVALID_LOCATION_ERROR")
    return {
        "status":"EXPORT_METADATA_FRESH" if age<=max_age else "EXPORT_STALE",
        "age_seconds":age,
        "operator_exists":loc["operator"]["exists"],
        "operator_contents_read":False,
        "telegram_health_proven":False,
        "public_publication":"OFF",
    }

def load(path):
    path=pathlib.Path(path)
    if path.name!="rg_news_health_public.json":
        raise HealthError("INVALID_EXPORT_NAME")
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0)
    try:
        fd=os.open(path,flags)
        with os.fdopen(fd,"rb") as stream:
            meta=os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size>16384:
                raise HealthError("UNSAFE_EXPORT_FILE")
            data=stream.read(16385)
            if len(data)>16384:raise HealthError("EXPORT_TOO_LARGE")
            return json.loads(data.decode("utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError):
        raise HealthError("EXPORT_NOT_AVAILABLE_OR_INVALID") from None

def selftest():
    import tempfile
    doc={
        "schema":SCHEMA,"generated_at_unix":1000000,
        "contains_secrets":False,"private_messages_read":0,
        "telegram_api_calls":0,"publications":0,
        "source":"LOCAL_NAS_METADATA_ONLY",
        "locations":{k:{"exists":False} for k in EXPECTED_LABELS},
    }
    assert evaluate(doc,now=1000001)["status"]=="EXPORT_METADATA_FRESH"
    assert evaluate(doc,now=1001201)["status"]=="EXPORT_STALE"
    assert evaluate(doc,now=1000001)["telegram_health_proven"] is False
    import copy
    for mutate in [
        lambda x:x.update(contains_secrets=True),
        lambda x:x.update(private_messages_read=1),
        lambda x:x.update(generated_at_unix=True),
        lambda x:x["locations"].update(secret={"exists":True}),
    ]:
        bad=copy.deepcopy(doc);mutate(bad)
        try:evaluate(bad,now=1000001)
        except HealthError:pass
        else:raise AssertionError("INVALID_EXPORT_ACCEPTED")
    with tempfile.TemporaryDirectory() as d:
        path=pathlib.Path(d)/"rg_news_health_public.json"
        path.write_text(json.dumps(doc),encoding="utf-8")
        assert evaluate(load(path),now=1000001)["status"]=="EXPORT_METADATA_FRESH"
        path.unlink();path.symlink_to("/etc/passwd")
        try:load(path)
        except HealthError:pass
        else:raise AssertionError("SYMLINK_EXPORT_ACCEPTED")
    print("SANITIZED_CONSUMER_FRESHNESS_PASS")
    print("SANITIZED_CONSUMER_NO_FALSE_BOT_HEALTH_PASS")
    print("SANITIZED_CONSUMER_SECRET_FIELDS_REJECTED_PASS")
    print("SANITIZED_CONSUMER_SYMLINK_REJECTED_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["selftest","check"])
    p.add_argument("--path",default="/volume1/docker/RG_TELEGRAM_NEWS_EXPORT/rg_news_health_public.json")
    a=p.parse_args()
    if a.action=="selftest":selftest();return
    try:result=evaluate(load(a.path))
    except HealthError as e:
        result={"status":"EXPORT_UNAVAILABLE","reason":str(e)[:80],
                "telegram_health_proven":False,"public_publication":"OFF"}
    print(json.dumps(result,sort_keys=True))
    if result["status"]!="EXPORT_METADATA_FRESH":raise SystemExit(2)
if __name__=="__main__":main()
