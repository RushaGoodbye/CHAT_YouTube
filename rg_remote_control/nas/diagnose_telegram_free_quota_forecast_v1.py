#!/usr/bin/env python3
"""RG Telegram FREE incident forensic report (read-only; never touches queues).

Reads local Synology deployment status and one each of Cloudflare's official
KV and Durable Object analytics queries. Does not call a Worker, DO, KV,
Telegram API, any paid API, or make any modifications.
"""
import datetime
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path("/volume1/docker")
STATE = ROOT / "RG_NAS_STATE"
ENV = ROOT / "RG_ALERTS_DEPLOY" / "deploy.env"
WRANGLER = ROOT / "RG_ALERTS_DEPLOY" / "cloudflare-alerts" / "wrangler.toml"
GRAPHQL = "https://api.cloudflare.com/client/v4/graphql"
ALLOWED_ERRORS = (
    ("Exceeded allowed volume of requests in Durable Objects free tier", "DURABLE_OBJECTS_FREE_QUOTA"),
    ("KV get() limit exceeded for the day", "KV_FREE_READ_QUOTA"),
    ("KV put() limit exceeded for the day", "KV_FREE_WRITE_QUOTA"),
    ("Cloudflare quota", "CLOUDFLARE_QUOTA"),
)

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def local_text(path):
    try:
        if path.is_symlink() or path.stat().st_size > 4_000_000:
            return None
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None

def quota_category(text):
    raw = str(text or "")
    return [category for pattern, category in ALLOWED_ERRORS if pattern in raw]

def load_json(path):
    try:
        if path.is_symlink() or path.stat().st_size > 2_000_000:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None

def parse_iso(x):
    try:
        dt = datetime.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None

def read_env():
    raw = local_text(ENV)
    if not raw:
        raise RuntimeError("Cloudflare NAS credentials absent")
    keys = {}
    for line in raw.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip().strip('"').strip("'")
    token = keys.get("CLOUDFLARE_API_TOKEN") or keys.get("CF_API_TOKEN")
    toml = local_text(WRANGLER) or ""
    match = re.search(r'(?m)^\s*account_id\s*=\s*"([a-z0-9]{32})"\s*$', toml)
    if not token or not match:
        raise RuntimeError("Cloudflare API token or account ID absent")
    return token, match.group(1)

def graphql(token, query, variables):
    raw = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL, data=raw, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "RG-Telegram-FREE-Forensics/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            body = response.read(300_000)
        value = json.loads(body)
        if value.get("errors"):
            # Do not print the query or server responses (avoid leaking context).
            return {"unavailable": "GraphQL rejected query or insufficient analytics permission"}
        return value.get("data") or {}
    except urllib.error.HTTPError as error:
        return {"unavailable": "GraphQL HTTP " + str(error.code)}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return {"unavailable": "GraphQL timeout/network"}
        
def account_rows(data, dataset):
    accounts = (((data.get("viewer") or {}).get("accounts")) or [])
    if not accounts or not isinstance(accounts[0], dict):
        return []
    return accounts[0].get(dataset) or []

def local_status():
    keys = ("last_deploy_status", "deploy_stage", "live_smoke_status",
            "cloudflare_quota_detected_at", "cloudflare_quota_reason",
            "cloudflare_quota_resume_epoch", "scheduler_last_check_at")
    rows = {name: local_text(STATE / name) for name in keys}
    marker = rows.get("cloudflare_quota_resume_epoch")
    if marker:
        try:
            rows["resume_at_utc"] = datetime.datetime.fromtimestamp(
                int(marker), datetime.timezone.utc).isoformat()
        except (ValueError, OverflowError):
            rows["resume_at_utc"] = "invalid"
    candidates = [STATE/"last-live-smoke.json", ROOT/"RG_NAS_WORK"/"live-smoke.json"]
    evidence = []
    for path in candidates:
        j = load_json(path)
        if not isinstance(j, dict):
            continue
        when = parse_iso(j.get("checkedAt"))
        checks = [
            {"name": str(v.get("name") or ""), "category": quota_category(
                (v.get("detail") or {}).get("error") if isinstance(v.get("detail"), dict)
                else str(v.get("detail") or ""))}
            for v in j.get("checks", []) if isinstance(v, dict)
        ]
        evidence.append({
            "file": path.name, "checkedAt": j.get("checkedAt"),
            "age_minutes": round((datetime.datetime.now(datetime.timezone.utc)-when).total_seconds()/60)
                if when else None,
            "quota_evidence": [x for x in checks if x["category"]],
            "failed": j.get("failed", []),
        })
    rows["live_smoke_evidence"] = evidence
    return rows

def main():
    if len(sys.argv)>1 and sys.argv[1]=="selftest":
        assert quota_category("KV get() limit exceeded for the day") == ["KV_FREE_READ_QUOTA"]
        assert quota_category("Error: Exceeded allowed volume of requests in Durable Objects free tier.") == ["DURABLE_OBJECTS_FREE_QUOTA"]
        assert quota_category("Everything healthy") == []
        assert parse_iso("2026-10-11T10:01:00Z").year == 2026
        print(json.dumps({"selftest": "PASS", "requests": 0, "changed_files": 0}))
        return
    output = {"report": "RG_TELEGRAM_FREE_QUOTA_FORENSICS_V1",
              "checked_at_utc": now_iso(), "local": local_status()}
    try:
        token, account = read_env()
    except RuntimeError as error:
        output["cloudflare_analytics"] = {"unavailable": str(error)}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return
    day = datetime.datetime.now(datetime.timezone.utc).date()
    date_today = day.isoformat()
    date_prev = (day-datetime.timedelta(days=1)).isoformat()
    kv_query = """query($accountTag: string!, $start: Date, $end: Date) {
      viewer { accounts(filter: {accountTag: $accountTag}) {
        kvOperationsAdaptiveGroups(
          filter: {date_geq: $start, date_leq: $end}, limit: 1000
        ) {sum {requests} dimensions {date actionType}}
      }}}
    """
    do_query = """query($accountTag: string!, $yesterday: Date) {
      viewer { accounts(filter: {accountTag: $accountTag}) {
        durableObjectsInvocationsAdaptiveGroups(
          filter: {date_gt: $yesterday}, limit: 1000
        ) {sum {requests}}
      }}}
    """
    kv = graphql(token, kv_query, {"accountTag":account,"start":date_today,"end":date_today})
    obj = graphql(token, do_query, {"accountTag":account,"yesterday":date_prev})
    del token
    if "unavailable" in kv:
        kv_result = kv
    else:
        totals = {}
        for row in account_rows(kv, "kvOperationsAdaptiveGroups"):
            kind = str((row.get("dimensions") or {}).get("actionType") or "unknown")
            totals[kind] = totals.get(kind, 0) + int((row.get("sum") or {}).get("requests") or 0)
        kv_result = {"utc_date": date_today, "observed_requests_by_action": totals}
    if "unavailable" in obj:
        do_result = obj
    else:
        rows = account_rows(obj, "durableObjectsInvocationsAdaptiveGroups")
        do_result = {"utc_date": date_today,
                     "observed_requests": sum(int((x.get("sum") or {}).get("requests") or 0) for x in rows),
                     "group_count": len(rows)}
    output["cloudflare_analytics"] = {"KV":kv_result, "DurableObjects":do_result,
        "note": "Aggregated/sampled analytics, not authoritative free-plan billing counters"}
    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
