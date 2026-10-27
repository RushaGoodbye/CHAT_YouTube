#!/usr/bin/env python3
"""Read-only comparison of production candidates and NEWS RG shadow. No network or writes."""
import sqlite3,json,time,sys,pathlib
B=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
def openro(path):
    c=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5)
    c.execute("PRAGMA query_only=ON")
    return c
def cols(c,t):
    return [r[1] for r in c.execute('PRAGMA table_info("'+t+'")')]
def audit():
    d={"schema":"NEWS_RG_DB_GAP_AUDIT_V1","read_only":True,"db_writes":0,"telegram_calls":0,"publication_attempts":0}
    main=openro(B/"news.sqlite3"); shadow=openro(B/"operator/news_rg_editorial_shadow_v1.sqlite3")
    try:
        for label,c in (("main",main),("editorial",shadow)):
            tables=[x[0] for x in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
            counts={}
            for t in ("candidates","story_shadow","editorial_draft","source_cursor"):
                if t in tables: counts[t]=c.execute('select count(*) from "'+t+'"').fetchone()[0]
            d[label]={"tables":tables,"counts":counts}
        mc=cols(main,"candidates")
        fields=[f for f in ("id","source","source_id","status","created_at","photo_reviewed") if f in mc]
        if fields:
            order="created_at" if "created_at" in mc else "id"
            rows=main.execute("select "+",".join('"'+f+'"' for f in fields)+" from candidates order by "+order+" desc limit 5").fetchall()
            d["main"]["latest_candidates"]=[dict(zip(fields,r)) for r in rows]
        sc=cols(shadow,"story_shadow")
        fields=[f for f in ("key","channel","number","posted_at","status","queued_at") if f in sc]
        if fields:
            order="queued_at" if "queued_at" in sc else "posted_at"
            rows=shadow.execute("select "+",".join('"'+f+'"' for f in fields)+" from story_shadow order by "+order+" desc limit 5").fetchall()
            d["editorial"]["latest_stories"]=[dict(zip(fields,r)) for r in rows]
        if "source_cursor" in d["editorial"]["tables"]:
            last=shadow.execute("select max(last_scan_at) from source_cursor").fetchone()[0]
            d["editorial"]["source_cursor_age_minutes"]=round((time.time()-last)/60,1) if last else None
    finally:main.close();shadow.close()
    return d
if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:
        assert cols(sqlite3.connect(":memory:"),"none")==[]
        print("NEWS_RG_DB_GAP_SELFTEST_PASS")
    elif sys.argv[1:]==["inspect"]:
        try:print(json.dumps(audit(),ensure_ascii=False,indent=2,default=str))
        except Exception as exc:
            print(json.dumps({"status":"SAFE_STOP","error_type":type(exc).__name__,"db_writes":0}))
            sys.exit(1)
    else:raise SystemExit("selftest|inspect")
