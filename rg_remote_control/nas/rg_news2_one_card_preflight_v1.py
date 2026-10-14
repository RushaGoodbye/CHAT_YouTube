#!/usr/bin/env python3
"""Read-only News2 one-card preflight. No SQLite writes, token reads, or Telegram calls."""
import json, pathlib, sqlite3, urllib.parse, urllib.request, urllib.error, datetime, ipaddress, socket, sys
BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
CID="9d4b6be3e992e26388d09e06"
def main():
    result={"status":"BLOCKED","candidate_id":CID,"image_verified":False,"exclusive_owner_verified":False,"ready_to_send":False,"telegram_calls":0,"db_writes":0,"reasons":[]}
    dbp=BASE/"news.sqlite3"
    if not dbp.is_file(): result["reasons"].append("DB_MISSING")
    else:
        uri="file:"+urllib.parse.quote(str(dbp),safe="/")+"?mode=ro"
        try:
            with sqlite3.connect(uri,uri=True,timeout=4) as db:
                db.row_factory=sqlite3.Row
                row=db.execute("SELECT id,status,photo_url,photo_reviewed,caption,created_at FROM candidates WHERE id=?",(CID,)).fetchone()
                if row:
                    result.update({k:row[k] for k in ("id","status","photo_reviewed","created_at")})
                    result["caption_preview"]=str(row["caption"] or "")[:180]
                    url=str(row["photo_url"] or "")
                    result["photo_url"]=url
                    p=urllib.parse.urlsplit(url)
                    allowed={"uimg.pravda.com.ua","static.ukrinform.com"}
                    if p.scheme!="https" or p.hostname not in allowed or p.username or p.password:
                        result["reasons"].append("UNTRUSTED_IMAGE_URL")
                    else:
                        result["image_host_allowed"]=True
                        # Host-only preflight. Do not download or reuse arbitrary URL from DB.
                        result["image_download_not_attempted"]=True
                    if row["status"]!="awaiting_photo_review":result["reasons"].append("CANDIDATE_STATUS_CHANGED")
                else: result["reasons"].append("CANDIDATE_NOT_FOUND")
        except sqlite3.Error: result["reasons"].append("DB_SCHEMA_ERROR")
    for key,filename in (("moderation_gate","MODERATION_DELIVERY_ENABLED"),("owner_marker","NAS_EXCLUSIVE_OWNER_VERIFIED")):
        p=BASE/filename
        result[key+"_present"]=p.is_file() and not p.is_symlink()
    result["reasons"].extend(["HUMAN_IMAGE_REVIEW_REQUIRED","EXTERNAL_EXCLUSIVE_OWNER_PROOF_REQUIRED"])
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
