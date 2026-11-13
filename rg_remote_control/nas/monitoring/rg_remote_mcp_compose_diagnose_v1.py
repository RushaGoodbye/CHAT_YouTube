#!/usr/bin/env python3
"""Read-only, fail-closed inventory of four RG Remote MCP Compose containers.

No compose up/down/config, no docker exec, no network calls, no credentials printed.
"""
import argparse
import json
import os
import subprocess

SERVICES={
    "hub": "rg-nas-mcp-hub",
    "youtube-worker": "rg-mcp-youtube",
    "telegram-worker": "rg-mcp-telegram",
    "auto-edit-worker": "rg-mcp-auto-edit",
}
SCHEMA="RG_REMOTE_MCP_COMPOSE_INVENTORY_V1"
FORMAT='{{json .}}'
class Unsafe(ValueError):pass

def get_metadata(name):
    if name not in SERVICES.values():raise Unsafe("CONTAINER_NOT_ALLOWLISTED")
    proc=subprocess.run(["docker","inspect","--type","container","--format",FORMAT,name],
                        capture_output=True,text=True,timeout=12,check=False)
    if proc.returncode:return None
    if len(proc.stdout)>150000:raise Unsafe("DOCKER_METADATA_TOO_LARGE")
    data=json.loads(proc.stdout)
    if not isinstance(data,dict) or data.get("Name")!="/"+name:raise Unsafe("CONTAINER_NAME_MISMATCH")
    state=data.get("State");cfg=data.get("Config")
    if not isinstance(state,dict) or not isinstance(cfg,dict):raise Unsafe("DOCKER_METADATA_MISSING")
    labels=cfg.get("Labels") or {}
    if not isinstance(labels,dict):raise Unsafe("INVALID_COMPOSE_LABELS")
    return {"name":name,"running":state.get("Running") is True,
            "health":((state.get("Health") or {}).get("Status") or "none"),
            "project":labels.get("com.docker.compose.project"),
            "service":labels.get("com.docker.compose.service"),
            "privileged":((data.get("HostConfig") or {}).get("Privileged") is True)}

def summarize(records):
    if set(records)!=set(SERVICES):raise Unsafe("SERVICE_SET_MISMATCH")
    result={};projects=set()
    for service,expected in SERVICES.items():
        entry=records[service]
        if entry is None:
            result[service]={"present":False,"running":False,"health":"missing","compose_label_match":False}
            continue
        if entry["name"]!=expected:raise Unsafe("NAME_MISMATCH")
        ok=entry["service"]==service and isinstance(entry["project"],str) and entry["project"]!=""
        if ok:projects.add(entry["project"])
        result[service]={"present":True,"running":entry["running"],"health":entry["health"],
                         "compose_label_match":bool(ok),"privileged":entry["privileged"]}
    complete=len(projects)==1 and all(x["present"] and x["running"] and x["compose_label_match"] and
        not x["privileged"] and x["health"] in ("healthy","none") for x in result.values())
    return {"schema":SCHEMA,"read_only":True,
            "status":"COMPOSE_INVENTORY_PASS" if complete else "NOT_VERIFIED",
            "single_compose_project":len(projects)==1,"service_count":len(SERVICES),
            "services":result,"telegram_bot_health_proven":False,
            "public_runner_shutdown_allowed":False,"telegram_api_calls":0,"publications":0}

def selftest():
    records={k:{"name":v,"running":True,"health":"healthy","project":"rg_remote_mcp",
                "service":k,"privileged":False} for k,v in SERVICES.items()}
    assert summarize(records)["status"]=="COMPOSE_INVENTORY_PASS"
    changed=dict(records)
    changed["telegram-worker"]={**records["telegram-worker"],"project":"other"}
    assert summarize(changed)["status"]=="NOT_VERIFIED"
    changed=dict(records);changed["hub"]=None
    assert summarize(changed)["status"]=="NOT_VERIFIED"
    changed=dict(records);changed["auto-edit-worker"]={**records["auto-edit-worker"],"privileged":True}
    assert summarize(changed)["status"]=="NOT_VERIFIED"
    try:get_metadata("unrelated")
    except Unsafe:pass
    else:raise AssertionError("ARBITRARY_DOCKER_INSPECT_ALLOWED")
    print("RG_REMOTE_MCP_COMPOSE_OFFLINE_SELFTEST_PASS")
    print("RG_REMOTE_MCP_NO_MUTATION_NO_BOT_API_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("selftest","inspect"))
    a=p.parse_args()
    if a.action=="selftest":selftest();return 0
    if os.name=="nt":raise SystemExit("LINUX_NAS_REQUIRED")
    try:info=summarize({k:get_metadata(v) for k,v in SERVICES.items()})
    except (Unsafe,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        info={"schema":SCHEMA,"read_only":True,"status":"SAFE_STOP",
              "error_class":type(exc).__name__,"public_runner_shutdown_allowed":False,
              "telegram_api_calls":0,"publications":0}
    print(json.dumps(info,sort_keys=True))
    return 0 if info["status"]=="COMPOSE_INVENTORY_PASS" else 2

if __name__=="__main__":raise SystemExit(main())
