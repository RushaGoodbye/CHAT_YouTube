#!/usr/bin/env python3
"""RG Telegram News2 unified read-only 8-block NAS audit. No token reads, HTTP, polling or writes."""
import datetime,json,os,pathlib,sqlite3,subprocess,urllib.parse
R=pathlib.Path("/volume1/docker")
N=R/"RG_TELEGRAM_NEWS_2"
def state(p):
    return {"exists":p.exists(),"regular_file":p.is_file() and not p.is_symlink()}
def db():
    p=N/"news.sqlite3"
    if not p.is_file():return {"status":"MISSING"}
    uri="file:"+urllib.parse.quote(str(p),safe="/")+"?mode=ro"
    try:
        with sqlite3.connect(uri,uri=True,timeout=4) as conn:
            counts=dict(conn.execute("SELECT status,count(*) FROM candidates GROUP BY status"))
            ready=conn.execute("""SELECT count(*) FROM candidates c LEFT JOIN moderation_dispatch d
                 ON c.id=d.candidate_id WHERE c.status='awaiting_moderation'
                 AND c.photo_reviewed=1 AND d.candidate_id IS NULL""").fetchone()[0]
            dispatch=dict(conn.execute("SELECT state,count(*) FROM moderation_dispatch GROUP BY state"))
            missingphotos=conn.execute("SELECT count(*) FROM candidates WHERE photo_url IS NULL OR photo_url=''").fetchone()[0]
        return {"status":"OK","counts":counts,"ready_for_moderation":ready,"dispatch":dispatch,"missing_photo_links":missingphotos}
    except sqlite3.Error as exc:return {"status":"ERROR","class":type(exc).__name__}
def containers():
    docker="/usr/local/bin/docker"
    if not pathlib.Path(docker).exists():return {"status":"DOCKER_UNAVAILABLE"}
    try:
        proc=subprocess.run([docker,"ps","--format","{{.Names}}|{{.Status}}"],capture_output=True,text=True,timeout=15)
        items={}
        for line in proc.stdout.splitlines():
            if "|" not in line:continue
            name,status=line.split("|",1)
            if name.startswith(("rg-mcp-","rg-nas-mcp-","rg-telegram","rg-openai-tunnel")):
                items[name]=status
        return {"status":"OK" if proc.returncode==0 else "ERROR","containers":items}
    except (OSError,subprocess.TimeoutExpired) as exc:return {"status":"ERROR","class":type(exc).__name__}
def config():
    p=N/"moderation.json"
    if not p.is_file() or p.is_symlink():return {"valid":False}
    try:
        o=json.loads(p.read_text("utf-8"))
        chat=o.get("moderation_chat_id")
        mods=o.get("moderators")
        valid=isinstance(chat,int) and chat!=0 and isinstance(mods,list) and bool(mods) and all(isinstance(x,int) and x>0 for x in mods) and (chat<0 or chat in mods)
        return {"valid":valid,"chat_type":"group" if isinstance(chat,int) and chat<0 else "personal","moderators":len(mods) if isinstance(mods,list) else 0}
    except (OSError,ValueError,AttributeError):return {"valid":False}
def main():
    checks={
      "01_nas_docker":containers(),
      "02_scheduler":{"scheduler_script":state(R/"RG_NAS_SCHEDULER_TICK.sh"),
        "native_bot_script":state(R/"RG_TELEGRAM_STATE/rg_telegram_nas_native_bot_v01.py")},
      "03_telegram_api":{"webhook_last_known":"disabled_at_prior_readonly_check",
        "live_api_not_queried":True,"sole_getupdates_owner_verified":False,
        "nas_cutover_gate":state(R/"RG_SECRETS/rg_nas_telegram_cutover_enabled"),
        "nas_news2_owner_gate":state(N/"NAS_EXCLUSIVE_OWNER_VERIFIED"),
        "cf_freeze":state(R/"RG_SECRETS/rg_cf_moderation_handoff_freeze"),
        "cf_handoff_receipt":state(R/"RG_TELEGRAM_STATE/rg_cf_moderation_handoff_v1/deployed.json")},
      "04_ingestion":db(),
      "05_photos":{"photo_check_module":state(N/"rg_v37.py"),
         "actual_visual_review_not_verified":True},
      "06_moderation":{"module":state(N/"rg_moderation.py"),"config":config(),
         "delivery_gate":state(N/"MODERATION_DELIVERY_ENABLED")},
      "07_publication":{"module":state(N/"rg_v35.py"),
          "publication_gate":state(N/"PUBLISH_ENABLED"),"live_delivery_unverified":True},
      "08_automation":{"scheduler":state(R/"RG_NAS_SCHEDULER_TICK.sh"),
          "kyiv_alert_delivery_unverified":True,"minute_silence_delivery_unverified":True}
    }
    print(json.dumps({"schema":"RG_TELEGRAM_NEWS2_UNIFIED_AUDIT_V1",
       "checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
       "read_only":True,"telegram_sends":0,"telegram_polls":0,"writes":0,
       "checks":checks,"ready_for_cutover":False,
       "caveat":"Local evidence does not establish exclusive polling or actual Telegram delivery."},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
