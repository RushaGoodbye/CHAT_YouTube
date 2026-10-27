#!/usr/bin/env python3
"""Read-only NEWS RG freshness diagnosis. Does not alter scheduler or bot."""
import json, pathlib, sqlite3, sys, time, datetime
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
DB=ROOT/"operator/news_rg_editorial_shadow_v1.sqlite3"
def main():
    if sys.argv[1:]==["selftest"]:
        assert 3600*4==14400
        print("NEWS_RG_FRESHNESS_DIAG_SELFTEST_PASS");return
    if sys.argv[1:]!=["inspect"]:raise SystemExit("selftest|inspect")
    out={"schema":"NEWS_RG_FRESHNESS_DIAG_V1","read_only":True,"telegram_calls":0,"db_writes":0,"publications":0}
    try:
        now=int(time.time())
        out["nas_time_utc"]=datetime.datetime.utcfromtimestamp(now).isoformat()+"Z"
        db=sqlite3.connect(DB.as_uri()+"?mode=ro",uri=True,timeout=5)
        db.execute("PRAGMA query_only=ON")
        for table in ("source_cursor","story_shadow"):
            out[table+"_columns"]=[x[1] for x in db.execute("PRAGMA table_info("+table+")")]
            out[table+"_rows"]=db.execute("SELECT count(*) FROM "+table).fetchone()[0]
        columns=out["source_cursor_columns"]
        if columns:
            rows=db.execute("SELECT * FROM source_cursor LIMIT 5").fetchall()
            out["source_cursor_preview"]=[{columns[i]: ("<redacted>" if any(w in columns[i].lower() for w in ("token","key","secret","password")) else val) for i,val in enumerate(row)} for row in rows]
        recent=db.execute("SELECT max(posted_at),min(posted_at) FROM story_shadow").fetchone()
        out["latest_story_age_hours"]=round((now-recent[0])/3600,2) if recent[0] else None
        db.close()
        out["expected_python_modules"]={n:(ROOT/n).is_file() for n in ("telegram_photo_review_flow.py","operator/news_rg_editorial_rewrite_shadow_v1.py")}
        print(json.dumps(out,ensure_ascii=False,indent=2,default=str))
    except Exception as exc:
        print(json.dumps({"status":"SAFE_STOP","error_type":type(exc).__name__,"telegram_calls":0,"db_writes":0,"publications":0}))
        sys.exit(1)
if __name__=="__main__":main()
