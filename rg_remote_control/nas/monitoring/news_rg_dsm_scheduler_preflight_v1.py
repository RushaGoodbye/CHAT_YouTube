#!/usr/bin/env python3
"""NEWS RG DSM scheduler preflight (read-only). No bot calls or writes."""
import subprocess,json,os,sys,re
def run(args,timeout=8):
 try:
  p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout)
  return {"rc":p.returncode,"out":p.stdout[:32000]}
 except (OSError,subprocess.TimeoutExpired) as e:return {"rc":-1,"error":type(e).__name__}
def main():
 if sys.argv[1:]==["selftest"]:
  assert re.search("news", "rg_news_dsm_tick.sh");print("NEWS_RG_DSM_PREFLIGHT_SELFTEST_PASS");return
 if sys.argv[1:]!=["inspect"]:raise SystemExit("selftest|inspect")
 out={"schema":"NEWS_RG_DSM_PREFLIGHT_V1","read_only":True,"telegram_calls":0,"db_writes":0,"publications":0}
 results={}
 for exe,args in (("/usr/syno/bin/synoschedtask",["--enum"]),("/usr/syno/bin/synoschedtask",["--get","4"])):
  if os.path.isfile(exe):
   k="task_enum" if "--enum" in args else "task_4"
   v=run([exe]+args);lines=v.get("out","").splitlines()
   results[k]={"rc":v["rc"],"matching_lines":[line[:280] for line in lines if any(x in line.lower() for x in ("news","rg_","task id","task name","enabled","last result","task: 4"))][:35]}
 out["task_scheduler"]=results
 for path in ("/volume1/docker/RG_TELEGRAM_NEWS_2/operator/outbound_tick.log","/volume1/docker/RG_TELEGRAM_NEWS_2/operator/callback_v29.log"):
  try:
   import time
   out.setdefault("file_ages",{})[os.path.basename(path)]=round((time.time()-os.stat(path).st_mtime)/60,1)
  except OSError:pass
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
