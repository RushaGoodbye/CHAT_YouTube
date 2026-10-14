"""Fail-closed News2 moderation readiness check. No Telegram API / sends / token reads."""
from __future__ import annotations
import json
import pathlib
import sqlite3
import sys
from urllib.parse import quote

BASE = pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
OUT = ("awaiting_moderation", "awaiting_photo_review", "legacy_hold", "approved_for_publication")

def main():
    import rg_news
    db_file = BASE / "news.sqlite3"
    report = {"schema":"RG_NEWS2_MODERATION_READINESS_V1","ready_to_send":False,
              "poll_owner_exclusive_verified":False,"channel_sends":0,"poll_calls":0,
              "config_exists":(BASE/"moderation.json").is_file(),
              "moderation_gate_present":(BASE/"MODERATION_DELIVERY_ENABLED").is_file(),
              "owner_marker_present":(BASE/"NAS_EXCLUSIVE_OWNER_VERIFIED").is_file(),
              "candidate_counts":{}, "eligible":0,"reason":[]}
    if not db_file.is_file():
        report["reason"].append("NEWS_DB_MISSING")
    else:
        uri="file:"+quote(str(db_file),safe="/")+"?mode=ro"
        try:
            with sqlite3.connect(uri,uri=True,timeout=3) as db:
                report["candidate_counts"]={str(status):int(n) for status,n in db.execute("SELECT status,count(*) FROM candidates GROUP BY status")}
                report["eligible"]=int(db.execute("""SELECT count(*) FROM candidates c
                    LEFT JOIN moderation_dispatch d ON c.id=d.candidate_id
                    WHERE c.status='awaiting_moderation' AND c.photo_reviewed=1 AND d.candidate_id IS NULL""").fetchone()[0])
        except sqlite3.Error as ex:
            report["reason"].append("SCHEMA_OR_QUERY_UNAVAILABLE")
    cfg = BASE/"moderation.json"
    if cfg.is_file() and not cfg.is_symlink():
        try:
            x=json.loads(cfg.read_text("utf-8"))
            valid=isinstance(x.get("moderation_chat_id"),int) and bool(x.get("moderators")) and all(isinstance(m,int) and m>0 for m in x["moderators"])
            report["moderation_config_valid"]=bool(valid and (x["moderation_chat_id"]<0 or x["moderation_chat_id"] in x["moderators"]))
            report["moderation_chat_type"]="group" if x.get("moderation_chat_id",0)<0 else "personal"
            report["moderator_count"]=len(x.get("moderators",[]))
        except (ValueError,TypeError,AttributeError):
            report["moderation_config_valid"]=False
    else:
        report["moderation_config_valid"]=False
    # Presence of marker is NOT exclusive ownership evidence. Never auto-trust it.
    report["reason"].append("EXCLUSIVE_GETUPDATES_OWNER_NOT_EXTERNALLY_VERIFIED")
    if not report["eligible"]:report["reason"].append("NO_PHOTO_REVIEWED_READY_CANDIDATE")
    if not report["moderation_config_valid"]:report["reason"].append("MODERATION_CONFIG_NOT_VALIDATED")
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
