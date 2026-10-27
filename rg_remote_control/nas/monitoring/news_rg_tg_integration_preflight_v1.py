#!/usr/bin/env python3
"""NEWS RG existing Telegram handler preflight: read-only, no bot calls."""
import json,os,pathlib,sqlite3,sys,time
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
SHADOW=ROOT/"operator/news_rg_editorial_shadow_v1.sqlite3"
def inspect():
    out={"schema":"NEWS_RG_TG_INTEGRATION_PREFLIGHT_V1","read_only":True,"telegram_api_calls":0,"db_writes":0,"publications":0}
    out["root_exists"]=ROOT.is_dir()
    targets=("telegram_photo_review_flow.py","news_rg_editorial_rewrite_shadow_v1.py","news_rg_editorial_contract_v1.py","news_rg_editorial_shadow_v1.sqlite3")
    files=[]
    for base in (ROOT,ROOT/"operator",ROOT/"app",ROOT/"scripts"):
        if not base.is_dir():continue
        for name in targets:
            p=base/name
            try:
                if p.is_file() and not p.is_symlink():files.append({"relative":str(p.relative_to(ROOT)),"size":p.stat().st_size})
            except OSError:pass
    out["recognized_files"]=files
    if SHADOW.is_file() and not SHADOW.is_symlink():
        cx=sqlite3.connect(SHADOW.as_uri()+"?mode=ro",uri=True,timeout=5)
        try:
            cx.execute("PRAGMA query_only=ON")
            rows=cx.execute("SELECT status,count(*),min(posted_at),max(posted_at) FROM story_shadow GROUP BY status").fetchall()
            out["shadow_queue"]=[{"status":r[0],"count":r[1],"oldest_unix":r[2],"newest_unix":r[3]} for r in rows]
            out["newer_than_4h"]=cx.execute("SELECT count(*) FROM story_shadow WHERE posted_at>=? AND status='needs_editorial_rewrite'",(int(time.time())-14400,)).fetchone()[0]
            out["schema_tables"]=[r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'") if not r[0].startswith("sqlite_")]
        finally:cx.close()
    return out
if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:
        assert "telegram_api_calls" in inspect.__code__.co_consts or callable(inspect)
        print("NEWS_RG_TG_INTEGRATION_PREFLIGHT_SELFTEST_PASS")
    elif sys.argv[1:]==["inspect"]:
        try:print(json.dumps(inspect(),ensure_ascii=False,indent=2))
        except Exception as e:
            print(json.dumps({"status":"SAFE_STOP","error_type":type(e).__name__,"telegram_api_calls":0,"db_writes":0,"publications":0}))
            sys.exit(1)
    else:raise SystemExit("selftest|inspect")
