#!/usr/bin/env python3
"""Root-only read-only Docker inventory -> tiny private-runner-safe export.

Only persistent modification is one sanitized JSON status file. No Docker mutations.
"""
import argparse, json, os, stat, subprocess, tempfile, time
from pathlib import Path

DEST=Path("/volume1/docker/RG_TELEGRAM_NEWS_EXPORT")
FILE="rg_remote_mcp_compose_public.json"
SCHEMA="RG_REMOTE_MCP_COMPOSE_SANITIZED_V1"
SERVICES={"hub":"rg-nas-mcp-hub","youtube-worker":"rg-mcp-youtube",
          "telegram-worker":"rg-mcp-telegram","auto-edit-worker":"rg-mcp-auto-edit"}
class SafeStop(ValueError):pass

def inspect_one(expected):
    cmd=["docker","inspect","--type","container","--format",
         "{{json .}}",expected]
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                     timeout=12,text=True)
    if p.returncode!=0:return None
    if len(p.stdout)>180000:raise SafeStop("DOCKER_METADATA_OVERSIZE")
    d=json.loads(p.stdout)
    if d.get("Name")!="/"+expected:raise SafeStop("CONTAINER_MISMATCH")
    state=d.get("State") or {}
    cfg=d.get("Config") or {}
    labels=cfg.get("Labels") or {}
    return {"name":expected,"running":state.get("Running") is True,
            "health":(state.get("Health") or {}).get("Status") or "none",
            "project":labels.get("com.docker.compose.project"),
            "service":labels.get("com.docker.compose.service"),
            "privileged":(d.get("HostConfig") or {}).get("Privileged") is True}

def capture(provider=inspect_one,now=None):
    projects=set();statuses={}
    for name,container in SERVICES.items():
        d=provider(container)
        if d is None:
            statuses[name]={"present":False,"running":False,"health":"missing",
                            "label_match":False,"unprivileged":False}
            continue
        valid=(d["service"]==name and isinstance(d["project"],str) and
               1<=len(d["project"])<=128)
        if valid:projects.add(d["project"])
        health=d["health"]
        if health not in ("healthy","unhealthy","starting","none"):
            health="unknown"
        statuses[name]={"present":True,"running":d["running"],
            "health":health,"label_match":bool(valid),
            "unprivileged":d["privileged"] is False}
    ok=len(projects)==1 and all(x["present"] and x["running"] and
        x["label_match"] and x["unprivileged"] and
        x["health"] in ("healthy","none") for x in statuses.values())
    return {"schema":SCHEMA,"generated_at_unix":int(time.time() if now is None else now),
        "status":"COMPOSE_INVENTORY_PASS" if ok else "NOT_VERIFIED",
        "single_compose_project":len(projects)==1,"service_count":4,
        "services":statuses,"contains_secrets":False,
        "telegram_api_calls":0,"publications":0,
        "telegram_bot_health_proven":False,"public_runner_shutdown_allowed":False}

def export(doc,dest=DEST):
    if os.geteuid()!=0:raise SafeStop("ROOT_REQUIRED")
    if dest.is_symlink() or not dest.is_dir():raise SafeStop("DEST_NOT_DIRECTORY")
    info=dest.stat()
    if info.st_uid!=0 or info.st_mode&0o022:raise SafeStop("DEST_PERMISSIONS_UNSAFE")
    target=dest/FILE
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise SafeStop("TARGET_NOT_REGULAR")
    fd,tmp=tempfile.mkstemp(prefix=".rg-compose-",dir=str(dest))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            os.fchmod(f.fileno(),0o644)
            json.dump(doc,f,sort_keys=True,separators=(",",":"))
            f.write("\n")
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def selftest():
    sample={name:{"name":container,"running":True,"health":"healthy",
                  "project":"rg_remote_mcp","service":name,"privileged":False}
            for name,container in SERVICES.items()}
    def provide(container):
        return next(x for x in sample.values() if x["name"]==container)
    d=capture(provide,now=100000)
    assert d["status"]=="COMPOSE_INVENTORY_PASS"
    sample["hub"]["project"]="other"
    assert capture(provide,now=100000)["status"]=="NOT_VERIFIED"
    sample["hub"]["project"]="rg_remote_mcp"
    sample["auto-edit-worker"]["privileged"]=True
    assert capture(provide,now=100000)["status"]=="NOT_VERIFIED"
    print("RG_COMPOSE_SANITIZED_EXPORT_SELFTEST_PASS")
    print("NO_DOCKER_MUTATION_NO_TELEGRAM_API_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["selftest","write"])
    args=p.parse_args()
    if args.action=="selftest":selftest();return 0
    if os.geteuid()!=0:raise SystemExit("ROOT_REQUIRED")
    try:
        doc=capture()
        export(doc)
    except (SafeStop,OSError,ValueError,subprocess.TimeoutExpired) as e:
        print(json.dumps({"status":"SAFE_STOP","error_class":type(e).__name__,
                          "public_runner_shutdown_allowed":False}))
        return 2
    print(json.dumps({"status":doc["status"],"schema":SCHEMA,
         "service_count":4,"export":str(DEST/FILE),
         "public_runner_shutdown_allowed":False,"telegram_api_calls":0}))
    return 0 if doc["status"]=="COMPOSE_INVENTORY_PASS" else 2

if __name__=="__main__":raise SystemExit(main())
