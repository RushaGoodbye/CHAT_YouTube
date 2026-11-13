#!/usr/bin/env python3
"""Trusted NAS one-shot sanitized status for rg-mcp-telegram (no secrets).

Run only from a NAS administrator-owned scheduled task. Does not read logs,
environment, container mounts, networks, or Telegram credentials.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

DEST_DIR=Path("/volume1/docker/RG_TELEGRAM_NEWS_EXPORT")
DEST=DEST_DIR/"rg_mcp_status_public.json"
ALLOWED_STATES={"running","exited","paused","restarting","created","dead","missing","unknown"}
ALLOWED_HEALTH={"healthy","unhealthy","starting","none","unknown"}
SCHEMA="RG_MCP_NAS_SANITIZED_STATUS_V1"

def inspect(docker="docker"):
    p=subprocess.run([docker,"inspect","rg-mcp-telegram","--format",
                      "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"],
                     capture_output=True,text=True,timeout=8,check=False)
    if p.returncode!=0:
        return "missing","unknown"
    parts=p.stdout.strip().split("|")
    if len(parts)!=2:return "unknown","unknown"
    state,health=parts
    if state not in ALLOWED_STATES or health not in ALLOWED_HEALTH:return "unknown","unknown"
    return state,health

def payload(state,health,now=None):
    assert state in ALLOWED_STATES and health in ALLOWED_HEALTH
    return {"schema":SCHEMA,"generated_at_unix":int(time.time() if now is None else now),
       "container":"rg-mcp-telegram","container_state":state,"health_state":health,
       "credential_fields_present":False,"telegram_api_calls":0,"publications":0}

def publish(doc,dirpath=DEST_DIR):
    folder=Path(dirpath)
    if folder.is_symlink() or not folder.is_dir():raise RuntimeError("EXPORT_DIR_NOT_PROVISIONED")
    if folder.stat().st_mode & 0o002:raise RuntimeError("WORLD_WRITABLE_EXPORT_DIR")
    if (folder/"rg_mcp_status_public.json").is_symlink():raise RuntimeError("SYMLINK_EXPORT_FORBIDDEN")
    fd,temp=tempfile.mkstemp(prefix=".rg_mcp_status.",suffix=".tmp",dir=folder)
    try:
        with os.fdopen(fd,"w") as f:
            json.dump(doc,f,sort_keys=True,separators=(",",":"))
            f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o644)
        os.replace(temp,folder/"rg_mcp_status_public.json")
    finally:
        if os.path.exists(temp):os.unlink(temp)

def selftest():
    assert payload("running","healthy",100)["generated_at_unix"]==100
    assert payload("missing","unknown",100)["container_state"]=="missing"
    assert payload("running","healthy",100)["telegram_api_calls"]==0
    with tempfile.TemporaryDirectory() as d:
        publish(payload("running","healthy",100),d)
        got=json.loads((Path(d)/"rg_mcp_status_public.json").read_text())
        assert got==payload("running","healthy",100)
        assert set(got)=={"schema","generated_at_unix","container","container_state","health_state",
                          "credential_fields_present","telegram_api_calls","publications"}
    print("RG_MCP_EXPORT_SANITIZED_SCHEMA_PASS")
    print("RG_MCP_EXPORT_ATOMIC_OFFLINE_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("selftest","write","inspect"))
    args=p.parse_args()
    if args.mode=="selftest":selftest()
    else:
        state,health=inspect()
        data=payload(state,health)
        if args.mode=="write":
            publish(data)
        print(json.dumps(data,sort_keys=True))
