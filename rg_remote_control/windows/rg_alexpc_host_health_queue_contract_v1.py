#!/usr/bin/env python3
"""Offline-only contract for one future AlexPC host health request.

No polling, no queue writes and no external commands. The live agent must
explicitly adopt this action before the private bridge may authorize it.
"""
import json
import re
from pathlib import Path

ACTION="inspect_alexpc_host_health_v1"
SCHEMA="RG_ALEXPC_READONLY_HEALTH_V1"
FIELDS={"schema","checked_at_utc","read_only","status","platform",
        "runner_listener_present","auto_edit_f_root_present",
        "auto_edit_runner_f_present","github_runner_c_present",
        "f_drive_free_gb","errors"}

class ContractError(ValueError):pass

def check_request(doc):
    if not isinstance(doc,dict) or set(doc)!={"request_id","action","args","timeout_seconds"}:
        raise ContractError("REQUEST_SCHEMA")
    if doc["action"]!=ACTION or doc["args"]!={}:
        raise ContractError("ACTION_OR_ARGUMENTS_NOT_ALLOWED")
    if not isinstance(doc["request_id"],str) or not re.fullmatch(r"gh-private-[0-9]{1,20}-[0-9]{1,5}",doc["request_id"]):
        raise ContractError("REQUEST_ID_INVALID")
    if type(doc["timeout_seconds"]) is not int or not 20<=doc["timeout_seconds"]<=120:
        raise ContractError("TIMEOUT_OUT_OF_RANGE")
    return True

def check_health(doc):
    if not isinstance(doc,dict) or set(doc)!=FIELDS:
        raise ContractError("HEALTH_SCHEMA")
    if doc["schema"]!=SCHEMA or doc["platform"]!="Windows" or doc["read_only"] is not True:
        raise ContractError("HEALTH_ORIGIN")
    if doc["status"] not in ("HOST_PRESENT","ATTENTION","UNKNOWN"):
        raise ContractError("STATUS_INVALID")
    for k in ("runner_listener_present","auto_edit_f_root_present",
              "auto_edit_runner_f_present","github_runner_c_present"):
        if type(doc[k]) is not bool:raise ContractError("BAD_BOOLEAN_"+k)
    f=doc["f_drive_free_gb"]
    if f is not None and (type(f) not in (int,float) or not 0<=f<=1000000):
        raise ContractError("BAD_FREE_SPACE")
    if not isinstance(doc["errors"],list) or len(doc["errors"])>5 or any(not isinstance(x,str) or len(x)>90 for x in doc["errors"]):
        raise ContractError("ERRORS_INVALID")
    if not isinstance(doc["checked_at_utc"],str) or len(doc["checked_at_utc"])>45:
        raise ContractError("TIMESTAMP_INVALID")
    return True

def selftest():
    request={"request_id":"gh-private-123456-1","action":ACTION,"args":{},"timeout_seconds":60}
    check_request(request)
    for key,val in (("action","run_shell"),("args",{"cmd":"whoami"}),("request_id","../../etc"),("timeout_seconds",3600)):
        bad=dict(request);bad[key]=val
        try:check_request(bad)
        except ContractError:pass
        else:raise AssertionError("UNSAFE_REQUEST_ACCEPTED "+key)
    health={"schema":SCHEMA,"checked_at_utc":"2026-11-13T14:51:19Z","read_only":True,
      "status":"HOST_PRESENT","platform":"Windows","runner_listener_present":True,
      "auto_edit_f_root_present":True,"auto_edit_runner_f_present":True,
      "github_runner_c_present":True,"f_drive_free_gb":76.5,"errors":[]}
    check_health(health)
    for key,val in (("read_only",False),("platform","Linux"),
                    ("runner_listener_present",1),("errors",["x"*91])):
        bad=dict(health);bad[key]=val
        try:check_health(bad)
        except ContractError:pass
        else:raise AssertionError("UNSAFE_RESULT_ACCEPTED "+key)
    print("ALEXPC_HOST_HEALTH_REQUEST_CONTRACT_PASS")
    print("ALEXPC_HOST_HEALTH_RESULT_SCHEMA_PASS")
    print("NO_QUEUE_DISPATCH_NO_EXECUTION_PASS")

if __name__=="__main__":
    import sys
    if sys.argv[1:]!=["selftest"]:raise SystemExit("SELFTEST_ONLY_NOT_A_LIVE_AGENT")
    selftest()
