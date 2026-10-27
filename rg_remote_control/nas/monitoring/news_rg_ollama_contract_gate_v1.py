#!/usr/bin/env python3
"""Read-only NEWS RG contract suitability audit, Python 3.8+.
No AI requests, Telegram calls, or database writes.
"""
import json,pathlib,sqlite3,sys,re
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_editorial_shadow_v1.sqlite3")
MIN_CHARS=500
MAX_CHARS=1000
def audit():
    if DB.is_symlink() or not DB.is_file():return {"status":"SHADOW_UNAVAILABLE"}
    db=sqlite3.connect(DB.as_uri()+"?mode=ro",uri=True,timeout=5)
    try:
        db.execute("PRAGMA query_only=ON")
        rows=db.execute("SELECT length(text),length(coalesce(media_url,'')),status FROM story_shadow").fetchall()
        pending=[(n,m) for n,m,s in rows if s=="needs_editorial_rewrite"]
        short=sum(n<MIN_CHARS for n,m in pending)
        withmedia=sum(m>0 for n,m in pending)
        return {"status":"READ_ONLY_OK","total":len(rows),"pending":len(pending),
                "pending_below_500_source_chars":short,"pending_with_media_url":withmedia,
                "policy_min_chars":MIN_CHARS,"policy_max_chars":MAX_CHARS,
                "important":"Source length does not prove that 500 factual characters can be generated. Short stories require rejection or linked independently verified information.",
                "ai_requests":0,"db_writes":0,"telegram_calls":0,"publications":0}
    finally:db.close()
def main():
    if sys.argv[1:]==["selftest"]:
        assert MIN_CHARS==500 and MAX_CHARS==1000
        print("NEWS_RG_CONTRACT_GATE_SELFTEST_PASS");return
    if sys.argv[1:]!=["inspect"]:raise SystemExit("selftest|inspect")
    try:print(json.dumps(audit(),ensure_ascii=False,indent=2))
    except (OSError,sqlite3.DatabaseError) as e:
        print(json.dumps({"status":"SAFE_STOP","error_type":type(e).__name__,"db_writes":0,"telegram_calls":0,"publications":0}))
        sys.exit(1)
if __name__=="__main__":main()
