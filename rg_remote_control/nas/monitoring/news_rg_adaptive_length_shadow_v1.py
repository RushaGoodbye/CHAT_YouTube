#!/usr/bin/env python3
"""Dry-run editorial length classifier. Does not change the production policy."""
import json, pathlib, sqlite3, sys
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_editorial_shadow_v1.sqlite3")
def classify(n):
    if n < 100: return "INSUFFICIENT_SOURCE_REVIEW"
    if n < 500: return "COMPACT_DRAFT_HUMAN_REVIEW"
    return "STANDARD_DRAFT_HUMAN_REVIEW"
def main():
    if sys.argv[1:]==["selftest"]:
        assert classify(99)=="INSUFFICIENT_SOURCE_REVIEW"
        assert classify(255)=="COMPACT_DRAFT_HUMAN_REVIEW"
        assert classify(500)=="STANDARD_DRAFT_HUMAN_REVIEW"
        print("NEWS_RG_ADAPTIVE_SHADOW_SELFTEST_PASS");return
    if sys.argv[1:]!=["inspect"]: raise SystemExit("selftest|inspect")
    try:
        if DB.is_symlink() or not DB.is_file():raise RuntimeError("DB_UNAVAILABLE")
        cx=sqlite3.connect(DB.as_uri()+"?mode=ro",uri=True,timeout=5)
        cx.execute("PRAGMA query_only=ON")
        rows=cx.execute("SELECT length(text) FROM story_shadow WHERE status='needs_editorial_rewrite'").fetchall()
        counts={k:0 for k in ("INSUFFICIENT_SOURCE_REVIEW","COMPACT_DRAFT_HUMAN_REVIEW","STANDARD_DRAFT_HUMAN_REVIEW")}
        for (n,) in rows:counts[classify(n or 0)]+=1
        cx.close()
        print(json.dumps({"schema":"NEWS_RG_ADAPTIVE_LENGTH_SHADOW_V1","status":"READ_ONLY_OK","counts":counts,"policy_unchanged":True,"note":"Character length is a triage signal, not a factual quality score. Never pad text to meet a length rule.","db_writes":0,"telegram_calls":0,"publications":0},ensure_ascii=False,indent=2))
    except (OSError,RuntimeError,sqlite3.DatabaseError) as e:
        print(json.dumps({"status":"SAFE_STOP","error_type":type(e).__name__,"db_writes":0,"telegram_calls":0,"publications":0}))
        sys.exit(1)
if __name__=="__main__":main()
