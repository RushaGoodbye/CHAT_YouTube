#!/usr/bin/env python3
"""NAS operator-only, fail-closed private GitHub runner transport migration.

This script never alters Telegram bot, existing public runner, private
operator permissions or credentials. It never reads credentials or request
contents. On successful migration it leaves stopped old container as rollback.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

PRIVATE="rg-nas-telegram-private-runner"
PUBLIC="rg-nas-telegram-runner"
IMAGE="rg-nas-github-runner:2.338.2"
RUNNER=Path("/var/services/homes/Alex Los/RG_NAS_RUNNER_DOCKER/private_runner")
EXPORT=Path("/volume1/docker/RG_TELEGRAM_NEWS_EXPORT")
BRIDGE=Path("/volume1/docker/RG_NAS_MCP/ALEXPC/auto_edit")

class Stop(RuntimeError):
    pass

def call(*args,check=True):
    p=subprocess.run(list(args),capture_output=True,text=True)
    if check and p.returncode:
        raise Stop("COMMAND_FAILED_"+str(args[0])+"_"+str(p.returncode))
    return p

def inspect(name):
    d=json.loads(call("docker","inspect",name).stdout)
    if len(d)!=1:raise Stop("CONTAINER_INSPECT_INVALID")
    return d[0]

def verify_path(path,expect_dir=True):
    if path.is_symlink() or not path.exists():
        raise Stop("PATH_MISSING_OR_SYMLINK_"+path.name)
    if expect_dir and not path.is_dir():
        raise Stop("NOT_A_DIRECTORY_"+path.name)

def preflight():
    if os.geteuid()!=0:raise Stop("ROOT_REQUIRED")
    verify_path(RUNNER)
    verify_path(EXPORT)
    if not (RUNNER/".runner").is_file() or not (RUNNER/".credentials").is_file():
        raise Stop("RUNNER_REGISTRATION_NOT_READY")
    registration=json.loads((RUNNER/".runner").read_text(encoding="utf-8-sig"))
    if registration.get("gitHubUrl","").rstrip("/")!="https://github.com/RushaGoodbye/rasha-goodbye-news-bot":
        raise Stop("WRONG_PRIVATE_REPOSITORY")
    verify_path(BRIDGE)
    for name in ("requests","results","errors"):
        verify_path(BRIDGE/name)
    public=inspect(PUBLIC)
    private=inspect(PRIVATE)
    if not public["State"]["Running"] or not private["State"]["Running"]:
        raise Stop("RUNNER_NOT_RUNNING")
    if private["Config"]["Image"]!=IMAGE:
        raise Stop("UNEXPECTED_PRIVATE_IMAGE")
    mounts={x["Destination"]:(x["Source"],x["RW"]) for x in private["Mounts"]}
    expected={"/runner":(str(RUNNER),True),"/nas-health":(str(EXPORT),False)}
    if mounts!=expected:
        raise Stop("UNEXPECTED_PRIVATE_MOUNTS")
    if private["HostConfig"]["Privileged"]:
        raise Stop("PRIVILEGED_CONTAINER")
    if private["Config"]["User"]!="1026:100":
        raise Stop("UNEXPECTED_RUNNER_USER")
    if private["Config"].get("Entrypoint")!=["/bin/bash"]:
        raise Stop("UNEXPECTED_ENTRYPOINT")
    if private["Config"].get("Cmd")!=["-c","./run.sh"]:
        raise Stop("UNEXPECTED_RUNNER_COMMAND")
    # Test 1026:100 access using the same immutable local runner image.
    probe=call("docker","run","--rm","--user","1026:100",
        "--mount","type=bind,source="+str(BRIDGE/"requests")+",target=/probe/requests",
        "--mount","type=bind,source="+str(BRIDGE/"results")+",target=/probe/results,readonly",
        "--mount","type=bind,source="+str(BRIDGE/"errors")+",target=/probe/errors,readonly",
        "--entrypoint","/bin/sh",IMAGE,"-c",
        'test -w /probe/requests && test -r /probe/results && test -r /probe/errors',
        check=False)
    if probe.returncode:
        raise Stop("BRIDGE_UID1026_PERMISSION_DENIED_NO_CHANGES")
    print("PREFLIGHT_PRIVATE_REGISTRATION_PASS")
    print("PREFLIGHT_PUBLIC_RUNNER_RUNNING_PASS")
    print("PREFLIGHT_BRIDGE_PERMISSIONS_PASS")
    print("PREFLIGHT_NO_OPERATOR_ACCESS_PASS")

def install():
    preflight()
    rollback=PRIVATE+"-rollback-"+time.strftime("%Y%m%d-%H%M%S")
    old_stopped=False
    old_renamed=False
    new_created=False
    try:
        call("docker","stop","--time","15",PRIVATE)
        old_stopped=True
        call("docker","rename",PRIVATE,rollback)
        old_renamed=True
        args=["docker","run","-d","--name",PRIVATE,
              "--restart","unless-stopped","--user","1026:100",
              "--security-opt","no-new-privileges:true","--cap-drop","ALL",
              "--mount","type=bind,source="+str(RUNNER)+",target=/runner",
              "--mount","type=bind,source="+str(EXPORT)+",target=/nas-health,readonly",
              "--mount","type=bind,source="+str(BRIDGE/"requests")+",target=/rg-bridge/requests",
              "--mount","type=bind,source="+str(BRIDGE/"results")+",target=/rg-bridge/results,readonly",
              "--mount","type=bind,source="+str(BRIDGE/"errors")+",target=/rg-bridge/errors,readonly",
              "--workdir","/runner","--entrypoint","/bin/bash",IMAGE,"-c","./run.sh"]
        call(*args)
        new_created=True
        time.sleep(8)
        running=inspect(PRIVATE)["State"]["Running"]
        if not running:raise Stop("NEW_PRIVATE_RUNNER_NOT_RUNNING")
        mounts={x["Destination"]:x["RW"] for x in inspect(PRIVATE)["Mounts"]}
        if mounts!={"/runner":True,"/nas-health":False,
                      "/rg-bridge/requests":True,
                      "/rg-bridge/results":False,
                      "/rg-bridge/errors":False}:
            raise Stop("NEW_CONTAINER_MOUNTS_MISMATCH")
        if not inspect(PUBLIC)["State"]["Running"]:
            raise Stop("PUBLIC_RUNNER_STOPPED_UNEXPECTEDLY")
        print("PRIVATE_RUNNER_MIGRATION_PASS")
        print("PRIVATE_AGENT_TRANSPORT_RW_REQUESTS_PASS")
        print("PRIVATE_AGENT_TRANSPORT_RO_RESULTS_ERRORS_PASS")
        print("PUBLIC_RUNNER_UNCHANGED_PASS")
        print("ROLLBACK_CONTAINER="+rollback)
        print("TELEGRAM_BOT_NOT_MODIFIED_PASS")
    except Exception:
        if new_created:
            call("docker","rm","-f",PRIVATE,check=False)
        if old_renamed:
            call("docker","rename",rollback,PRIVATE,check=False)
        if old_stopped:
            call("docker","start",PRIVATE,check=False)
        print("ROLLBACK_ATTEMPTED")
        raise

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["preflight","install"])
    v=p.parse_args()
    try:
        if v.action=="preflight":preflight()
        else:install()
    except Stop as e:
        print("SAFE_STOP="+str(e))
        raise SystemExit(2)

if __name__=="__main__":
    main()
