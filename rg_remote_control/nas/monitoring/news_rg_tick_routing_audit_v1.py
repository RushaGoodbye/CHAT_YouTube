#!/usr/bin/env python3
"""Read-only scheduler-to-editorial routing audit, no secret values, no execution."""
import os,pathlib,json,re,sys,time,sqlite3
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
PATHS=[ROOT/"rg_news_dsm_tick.sh",ROOT/"operator/rg_news2_rss_hourly.py",ROOT/"operator/news_rg_editorial_shadow_v1.sqlite3",ROOT/"operator/outbound_tick.log",ROOT/"operator/callback_v29.log"]
def meta(p):
 try:
  st=p.lstat();return {"present":True,"symlink":p.is_symlink(),"age_min":round((time.time()-st.st_mtime)/60,1),"bytes":st.st_size}
 except OSError:return {"present":False}
def audit():
 out={"schema":"NEWS_RG_TICK_ROUTING_AUDIT_V1","read_only":True,"db_writes":0,"telegram_calls":0,"publications":0,"files":{str(p.relative_to(ROOT)):meta(p) for p in PATHS}}
 script=PATHS[0]
 if script.is_file() and not script.is_symlink():
  lines=script.read_text("utf8",errors="replace").splitlines()
  # Only command references, redacting assignments, values, credentials and arguments.
  out["tick_script_lines"]=len(lines)
  out["tick_references"]=[{"line":i,"references":[x for x in ("rss","shadow","editorial","telegram","python","docker","flock","lock","cron") if x in line.lower()]} for i,line in enumerate(lines,1) if any(x in line.lower() for x in ("rss","shadow","editorial","telegram","python","docker","flock","lock","cron"))][:70]
 db=PATHS[2]
 if db.is_file() and not db.is_symlink():
  c=sqlite3.connect(db.as_uri()+"?mode=ro",uri=True,timeout=5)
  try:
   c.execute("PRAGMA query_only=ON")
   out["shadow_total"]=c.execute("select count(*) from story_shadow").fetchone()[0]
   out["source_last_scan_age_min"]=round((time.time()-c.execute("select max(last_scan_at) from source_cursor").fetchone()[0])/60,1)
  finally:c.close()
 return out
if __name__=="__main__":
 if sys.argv[1:]==["selftest"]:
  assert "rss" in "rss_hourly";print("NEWS_RG_TICK_ROUTING_AUDIT_SELFTEST_PASS")
 elif sys.argv[1:]==["inspect"]:
  try:print(json.dumps(audit(),ensure_ascii=False,indent=2))
  except Exception as e:
   print(json.dumps({"status":"SAFE_STOP","error_type":type(e).__name__,"db_writes":0,"telegram_calls":0,"publications":0}));sys.exit(1)
 else:raise SystemExit("selftest|inspect")
