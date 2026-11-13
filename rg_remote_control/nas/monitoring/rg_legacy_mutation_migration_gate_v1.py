#!/usr/bin/env python3
"""Offline source-verified fail-closed migration gate for legacy modifying actions.

The gate never dispatches, installs, stops, deploys or changes any runner.
"""
import argparse,json
from pathlib import Path

SOURCE=Path("rg_remote_control/task_runner.py")
WORKFLOW=Path(".github/workflows/rg-remote-control.yml")
AGENT_WORKFLOW=Path(".github/workflows/rg-nas-alexpc-agent-control.yml")
ACTIONS=("deploy_remote_mcp","sync_nas_scheduler_tick")
RESTRICTED=("auto_edit_","apply_auto_edit_","build_auto_edit_",
            "start_auto_edit_","launch_auto_edit_","finalize_auto_edit_")
def analyze(text,workflow,agent):
    if not all("def "+name+"(" in text for name in ACTIONS):
        return {"status":"SAFE_STOP_SOURCE_CHANGED","public_runner_shutdown_allowed":False}
    if "docker" not in text or "compose" not in text:
        return {"status":"SAFE_STOP_DEPLOY_IMPLEMENTATION_UNKNOWN","public_runner_shutdown_allowed":False}
    if not all(name in workflow for name in ACTIONS):
        return {"status":"SAFE_STOP_WORKFLOW_ACTION_CHANGED","public_runner_shutdown_allowed":False}
    if "runs-on: [self-hosted, rg, nas]" not in workflow or "runs-on: [self-hosted, rg, nas]" not in agent:
        return {"status":"SAFE_STOP_RUNNER_ROUTE_CHANGED","public_runner_shutdown_allowed":False}
    return {"schema":"RG_LEGACY_MUTATION_DENY_AUDIT_V1",
      "status":"LEGACY_MUTATING_ACTIONS_NOT_MIGRATED",
      "blocked_mutations":list(ACTIONS)+list(RESTRICTED),
      "legacy_public_workflows_checked":2,
      "migration_missing":["exact-action scoped private workflow","dry-run preflight",
         "production backup and rollback","isolated integration test",
         "live post-change acceptance"],
      "public_runner_shutdown_allowed":False,
      "production_writes":0,"telegram_api_calls":0}

def selftest():
    source="def deploy_remote_mcp():pass\ndef sync_nas_scheduler_tick():pass\ndocker compose"
    wf="runs-on: [self-hosted, rg, nas] deploy_remote_mcp sync_nas_scheduler_tick"
    agent="runs-on: [self-hosted, rg, nas] auto_edit_ apply_auto_edit_"
    assert analyze(source,wf,agent)["status"]=="LEGACY_MUTATING_ACTIONS_NOT_MIGRATED"
    assert analyze(source.replace("def deploy_remote_mcp","def renamed"),wf,agent)["status"].startswith("SAFE_STOP")
    assert not analyze(source,wf,agent)["public_runner_shutdown_allowed"]
    print("LEGACY_MUTATIONS_FAIL_CLOSED_AUDIT_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","audit"])
    a=p.parse_args()
    if a.mode=="selftest":selftest()
    else:
        d=analyze(SOURCE.read_text(),WORKFLOW.read_text(),AGENT_WORKFLOW.read_text())
        print(json.dumps(d,sort_keys=True,indent=2))
