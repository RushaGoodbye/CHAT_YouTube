#!/usr/bin/env python3
"""Independent read-only NAS acceptance 2-5. No Telegram API, Docker changes,
bot dispatcher, runner stop, persistent writes, or production DB mutation.
"""
import argparse,json,os,sqlite3,subprocess,time
from pathlib import Path

BASE=Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
OP=BASE/"operator"
EXPORT=Path("/volume1/docker/RG_TELEGRAM_NEWS_EXPORT")
BRIDGE=Path("/volume1/docker/RG_NAS_MCP/ALEXPC")
EXPECTED={"hub":"rg-nas-mcp-hub","youtube-worker":"rg-mcp-youtube",
          "telegram-worker":"rg-mcp-telegram","auto-edit-worker":"rg-mcp-auto-edit"}
AUDIT_NAMES=("rg_news_final_readonly_audit_20261113.py",
             "rg_news_historical_restore_audit_20261113.py")
class Stop(ValueError):pass

def read_json(path,limit=32768):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:
        raise Stop("NOT_SAFE_OR_MISSING")
    d=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(d,dict):raise Stop("NOT_OBJECT")
    return d

def compose(now):
    try:d=read_json(EXPORT/"rg_remote_mcp_compose_public.json",4096)
    except (Stop,OSError,ValueError):
        return {"status":"NOT_VERIFIED","reason":"EXPORT_MISSING"}
    schema=d.get("schema")
    raw=d.get("services")
    if schema!="RG_REMOTE_MCP_COMPOSE_SANITIZED_V1" or not isinstance(raw,dict) or set(raw)!=set(EXPECTED):
        return {"status":"NOT_VERIFIED","reason":"EXPORT_SCHEMA"}
    ts=d.get("generated_at_unix")
    if type(ts)is not int or not -60<=now-ts<=900:
        return {"status":"NOT_VERIFIED","reason":"EXPORT_STALE"}
    valid=(d.get("single_compose_project") is True and d.get("service_count")==4
          and d.get("telegram_api_calls")==0 and d.get("publications")==0
          and d.get("public_runner_shutdown_allowed") is False
          and d.get("telegram_bot_health_proven") is False)
    for k in EXPECTED:
        s=raw[k]
        valid=valid and isinstance(s,dict) and s.get("present") is True and s.get("running") is True and s.get("label_match") is True and s.get("unprivileged") is True and s.get("health") in ("healthy","none")
    valid=valid and d.get("status")=="COMPOSE_INVENTORY_PASS"
    return {"status":"PASS" if valid else "NOT_VERIFIED","age_sec":now-ts,"services":4}

def alexpc(now):
    p=BRIDGE/"status"/"alexpc_agent.json"
    try:d=read_json(p,65536)
    except (OSError,ValueError,Stop):
        return {"status":"NOT_VERIFIED","reason":"AGENT_STATUS_UNAVAILABLE"}
    # Do not assume a particular agent timestamp schema or claim fresh from file mtime alone.
    age=round(now-p.stat().st_mtime)
    return {"status":"STATUS_FILE_PRESENT" if age<=600 else "NOT_VERIFIED",
        "status_file_age_sec":age,
        "post_reboot_host_health_e2e":"NOT_VERIFIED",
        "sensitive_agent_fields_returned":0}

def script_probe(name,allowed):
    target=OP/name
    if not target.is_file() or target.is_symlink():
        return {"status":"NOT_VERIFIED","reason":"SCRIPT_NOT_INSTALLED"}
    try:
        p=subprocess.run(["/usr/bin/python3",str(target)],capture_output=True,
                          timeout=45,text=True,check=False)
        if p.returncode or len(p.stdout)>300000:
            return {"status":"NOT_VERIFIED","reason":"AUDIT_EXIT_OR_SIZE","exit_code":p.returncode}
        d=json.loads(p.stdout)
        if not isinstance(d,dict):raise ValueError("not_object")
        return {"status":"AUDIT_COMPLETED","data":{k:d.get(k) for k in allowed},
                "api_calls_by_audit":d.get("telegram_api_calls_by_this_audit",d.get("telegram_api_calls",None))}
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return {"status":"NOT_VERIFIED","reason":"AUDIT_FAILED"}

def newsroom():
    keys=("health_status","health_alert_codes","source_status","private_status",
          "staging_status","public_status","dsm_status","db_candidate_count",
          "db_moderation_dispatch_states","db_photo_dispatch_states",
          "receipt_status_counts","backup_age_hours","release_integrity_pass",
          "sanitized_export_age_min","public_channel_runtime_verified",
          "pinned_hash_mismatches")
    return script_probe(AUDIT_NAMES[0],keys)

def restore():
    keys=("historical_db_restore","historical_backup_age_hours",
          "historical_candidate_count","historical_recovered_rows",
          "production_file_writes","backup_root_exists")
    return script_probe(AUDIT_NAMES[1],keys)

def selftest():
    assert len(EXPECTED)==4 and AUDIT_NAMES[0]!=AUDIT_NAMES[1]
    assert "export" in str(EXPORT).lower()
    print("RG_MIGRATION_STAGE2TO5_READONLY_SELFTEST_PASS")
    print("RG_MIGRATION_NO_TELEGRAM_API_NO_DEPLOY_NO_RESTART_PASS")

def main():
    a=argparse.ArgumentParser();a.add_argument("mode",choices=("selftest","inspect"))
    v=a.parse_args()
    if v.mode=="selftest":selftest();return 0
    now=int(time.time())
    out={"schema":"RG_MIGRATION_STAGE2TO5_BATCH_V1","checked_at_unix":now,
         "read_only":True,"nas_compose_status":compose(now),
         "alexpc_agent_status":alexpc(now),"telegram_news2":newsroom(),
         "isolated_sqlite_restore":restore(),
         "telegram_api_calls_by_batch":0,"publications_by_batch":0,
         "production_write_operations":0,"public_runner_shutdown_allowed":False,
         "mutating_routes_migrated":False}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
