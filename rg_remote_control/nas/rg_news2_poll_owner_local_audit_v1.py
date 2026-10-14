#!/usr/bin/env python3
"""RG News2: read-only local Telegram polling inventory. No secrets, API calls or changes."""
import os,json,pathlib,subprocess,datetime
ROOT=pathlib.Path("/volume1/docker")
MARKERS=("getupdates","poll-once","rg_moderation.py","rg_v36.py","telegram_bot","telegram_poll")
def main():
    matches=[]
    proc=pathlib.Path("/proc")
    for p in proc.iterdir():
        if not p.name.isdigit():continue
        try:
            raw=(p/"cmdline").read_bytes().replace(b"\0",b" ").decode("utf-8","replace")
            low=raw.lower()
            if any(k in low for k in MARKERS):
                # Do not output command line; it may include private bot credentials.
                matches.append({"pid":int(p.name),"exe":os.path.basename(os.readlink(p/"exe")) if (p/"exe").exists() else "unknown","telegram_related":True})
        except (OSError,PermissionError):pass
    probes={}
    for name in ("RG_NAS_SCHEDULER_TICK.sh","RG_TELEGRAM_STATE/rg_telegram_nas_native_bot_v01.py","RG_TELEGRAM_NEWS_2/MODERATION_DELIVERY_ENABLED","RG_TELEGRAM_NEWS_2/NAS_EXCLUSIVE_OWNER_VERIFIED"):
        path=ROOT/name
        probes[name]={"present":path.exists(),"regular_file":path.is_file() and not path.is_symlink()}
    out={"schema":"RG_NEWS2_LOCAL_POLL_OWNER_AUDIT_V1","checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
         "local_matching_processes":matches[:40],"process_scan_count":len(matches),"files":probes,
         "cloudflare_getupdates_owner_verified":False,"other_hosts_verified":False,
         "sole_poll_owner_verified":False,"poll_calls":0,"telegram_sends":0,"writes":0,
         "next_step":"Cross-system ownership reconciliation required before enabling polling."}
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
