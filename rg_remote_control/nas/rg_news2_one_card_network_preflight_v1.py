#!/usr/bin/env python3
"""News2 cutover readiness (read only). Does not poll/getUpdates or send messages."""
import json, pathlib, sqlite3, urllib.parse, urllib.request, urllib.error
BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
ID="9d4b6be3e992e26388d09e06"
def main():
    report={"status":"BLOCKED","candidate_id":ID,"telegram_sends":0,"telegram_polls":0,
            "database_writes":0,"webhook":None,"image_http":None,"owner_exclusive":False,
            "photo_reviewed":False,"reasons":[]}
    uri="file:"+urllib.parse.quote(str(BASE/"news.sqlite3"),safe="/")+"?mode=ro"
    try:
        with sqlite3.connect(uri,uri=True,timeout=3) as db:
            row=db.execute("SELECT status,photo_url,photo_reviewed FROM candidates WHERE id=?",(ID,)).fetchone()
        if not row:report["reasons"].append("CANDIDATE_MISSING")
        else:
            status,url,reviewed=row
            report["candidate_status"]=status
            report["photo_reviewed"]=bool(reviewed)
            parts=urllib.parse.urlsplit(url or "")
            if parts.scheme=="https" and parts.hostname=="uimg.pravda.com.ua" and not parts.username and not parts.password:
                try:
                    req=urllib.request.Request(url,method="HEAD",headers={"User-Agent":"RG-News2-preflight/1.0"})
                    with urllib.request.urlopen(req,timeout=9) as resp:
                        report["image_http"]={"code":resp.status,
                          "content_type":resp.headers.get("Content-Type","").split(";")[0],
                          "content_length":resp.headers.get("Content-Length")}
                except Exception as e:report["image_http"]={"error_type":type(e).__name__}
            else:report["reasons"].append("IMAGE_HOST_NOT_ALLOWED")
    except (sqlite3.Error,OSError) as e:report["reasons"].append("DB_"+type(e).__name__)
    tokenfile=pathlib.Path("/volume1/docker/RG_SECRETS/rg_telegram_bot_token")
    if tokenfile.is_file() and not tokenfile.is_symlink():
        try:
            token=tokenfile.read_text().strip()
            if token:
                req=urllib.request.Request("https://api.telegram.org/bot"+token+"/getWebhookInfo",headers={"User-Agent":"RG-News2-preflight/1.0"})
                with urllib.request.urlopen(req,timeout=10) as resp:
                    raw=json.loads(resp.read(16384))
                result=raw.get("result",{})
                report["webhook"]={"configured":bool(result.get("url")),
                    "pending_update_count":result.get("pending_update_count")}
            else:report["reasons"].append("EMPTY_BOT_TOKEN")
        except Exception as e:report["webhook"]={"error_type":type(e).__name__}
    else:report["reasons"].append("BOT_TOKEN_FILE_UNAVAILABLE")
    report["owner_marker_present"]=(BASE/"NAS_EXCLUSIVE_OWNER_VERIFIED").is_file()
    report["moderation_gate_present"]=(BASE/"MODERATION_DELIVERY_ENABLED").is_file()
    report["reasons"].append("SOLE_GETUPDATES_POLLING_OWNER_UNVERIFIED")
    report["reasons"].append("ORIGINAL_PHOTO_VISUAL_REVIEW_REQUIRED")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
