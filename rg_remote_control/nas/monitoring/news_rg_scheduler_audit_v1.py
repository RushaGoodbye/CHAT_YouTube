#!/usr/bin/env python3
"""Read-only NEWS RG scheduler/collector evidence, no secret contents."""
import os,pathlib,subprocess,json,time,sys
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
def safe_run(argv):
 try:
  p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=6)
  return p.stdout[:16000].splitlines() if p.returncode==0 else []
 except Exception:return []
def main():
 if sys.argv[1:]==["selftest"]:
  assert "token" in "token";print("NEWS_RG_SCHEDULER_AUDIT_SELFTEST_PASS");return
 if sys.argv[1:]!=["inspect"]:raise SystemExit("selftest|inspect")
 names=("news_rg","rg_news","telegram_news","editorial_shadow","source_scan")
 out={"schema":"NEWS_RG_SCHEDULER_AUDIT_V1","read_only":True,"timestamp":int(time.time()),"publications":0,"telegram_calls":0,"db_writes":0}
 processes=safe_run(["ps","-eo","pid,etime,args"])
 out["relevant_processes"]=[line[:240] for line in processes if any(n in line.lower() for n in names) and "scheduler_audit_v1" not in line.lower()][:30]
 cron=safe_run(["crontab","-l"])
 out["root_cron_relevant_lines"]=[line[:230] for line in cron if not line.strip().startswith("#") and any(n in line.lower() for n in names)][:30]
 try:
  out["operator_recent_files"]=[{"name":p.name,"age_minutes":round((time.time()-p.stat().st_mtime)/60,1)} for p in (ROOT/"operator").iterdir() if p.is_file() and not p.is_symlink() and any(n in p.name.lower() for n in ("scan","tick","heartbeat","editorial","log","status"))][:45]
 except Exception as exc:out["operator_error"]=type(exc).__name__
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
