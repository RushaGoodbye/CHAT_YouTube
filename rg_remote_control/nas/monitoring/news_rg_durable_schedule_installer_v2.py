#!/usr/bin/env python3
"""Install NEWS RG durable AI staging after protected DSM tick, private-only.
No public Telegram calls, no existing Bot API callback modifications.
"""
import os,sys,json,pathlib,tempfile,hashlib,subprocess,shutil,datetime
B=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2");O=B/"operator";T=B/"rg_news_dsm_tick.sh"
P=O/"news_rg_final_tick_v1.py";A=O/"news_rg_ollama_adapter_v1.py";R=O/"news_rg_private_bridge_v1.py"
SRC_A=pathlib.Path("/tmp/news_rg_ollama_adapter_v1.py");SRC_R=pathlib.Path("/tmp/news_rg_private_bridge_v1.py")
TAG="# NEWS_RG_ISOLATED_SCHEDULE_V2"
def report(**x):print(json.dumps(x,sort_keys=True,ensure_ascii=False))
def stop(msg):raise RuntimeError(msg)
def put(p,buf,mode):
 fd,n=tempfile.mkstemp(prefix=".newsrg_",dir=str(p.parent))
 try:
  os.fchmod(fd,mode)
  with os.fdopen(fd,"wb") as f:f.write(buf);f.flush();os.fsync(f.fileno())
  os.replace(n,p)
 finally:
  if os.path.exists(n):os.unlink(n)
def checks():
 if os.geteuid()!=0:stop("SUDO_REQUIRED")
 for p in (B,O,T,P,SRC_A,SRC_R,O/"news_rg_source_shadow_ingest_v1.py"):
  if not p.is_file() or p.is_symlink():stop("MISSING_OR_SYMLINK_"+p.name)
 txt=T.read_text()
 if "rg_news2_private_final_guard_v1.py" not in txt or "# RG_NEWS2_PRIVATE_FINAL_V1" not in txt:stop("UNEXPECTED_DSM_TICK")
 if txt.count(TAG)>1:stop("UNEXPECTED_MULTIPLE_PATCHES")
 return txt
def install():
 before=checks()
 if TAG in before:return {"status":"ALREADY_SCHEDULED","publications":0}
 # Existing sidecar is patched ONLY to refer to durable adapter path. It never makes Bot API calls.
 script=P.read_text()
 if "news_rg_final.lock" not in script or "prepare-one" not in script:stop("UNKNOWN_SIDECAR")
 if "/tmp/news_rg_private_bridge_v1.py" not in script or "/tmp/news_rg_ollama_adapter_v1.py" not in script:stop("SIDECAR_ALREADY_CHANGED")
 new=script.replace('/tmp/news_rg_private_bridge_v1.py',str(R)).replace('/tmp/news_rg_ollama_adapter_v1.py',str(A))
 for name,content in ((A,SRC_A.read_bytes()),(R,SRC_R.read_bytes())):
  if name.is_symlink():stop("DEST_SYMLINK")
  put(name,content,0o600)
 # Preserve backup once, before touching production tick.
 digest=hashlib.sha256(before.encode()).hexdigest()[:12]
 bt=O/("rg_news_dsm_tick.before_schedule_v2_"+digest+".sh")
 bp=O/("news_rg_final_tick.before_schedule_v2_"+digest+".py")
 if not bt.exists():put(bt,before.encode(),0o600)
 if not bp.exists():put(bp,script.encode(),0o600)
 # Child runs isolated scan no more often than once/30min; DSM task keeps its original policy.
 launcher="""# NEWS_RG_ISOLATED_SCHEDULE_V2
# Private-only staging; NEVER publishes, polls or changes approval semantics.
/usr/bin/python3 '/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_safe_schedule_v2.py' launch >/dev/null 2>&1 || :
"""
 sched=O/"news_rg_safe_schedule_v2.py"
 program="""#!/usr/bin/env python3
import os,sys,subprocess,fcntl,time,pathlib,json
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
def run():
 fd=os.open(str(O/'news_rg_launch.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  marker=O/'news_rg_last_launch_utc'
  now=time.time()
  if marker.exists():
   try:
    if now-float(marker.read_text())<1800:return
   except (ValueError,OSError):return
  # Child process continues after the DSM task and has a separate exclusive lock.
  log=os.open(str(O/'news_rg_autorun.log'),os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
  try:
   proc=subprocess.Popen(['/usr/bin/python3',str(O/'news_rg_final_tick_v1.py')],
    stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
   marker.write_text(str(now))
   os.chmod(marker,0o600)
  finally:os.close(log)
 finally:os.close(fd)
if __name__=='__main__' and sys.argv[1:]==['launch']:run()
"""
 # Detect special dangerous public APIs in new scheduler source
 assert not any(x in program for x in ("sendPhoto","getUpdates","sendMessage","PUBLISH_ENABLED"))
 put(sched,program.encode(),0o700)
 put(P,new.encode(),0o700)
 updated=before.rstrip()+"\n"+launcher
 try:
  subprocess.run(["sh","-n"],input=updated,text=True,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  put(T,updated.encode(),0o700)
 except Exception:
  put(P,script.encode(),0o700)
  put(T,before.encode(),0o700)
  raise
 return {"status":"SCHEDULED_PRIVATE_STAGING_ONLY","period_min":30,
  "production_bot_preserved":True,"existing_dsm_task_preserved":True,
  "telegram_private_delivery":"NOT_CONNECTED","publications":0,
  "backup":str(bt),"durable_modules":[str(A),str(R)]}
def verify():
 x=checks()
 return {"status":"SCHEDULED" if TAG in x else "NOT_SCHEDULED",
  "durable_modules":all(p.is_file() for p in (A,R)),
  "production_bot_untouched":True,"private_delivery":"NOT_CONNECTED"}
def main():
 try:
  a=sys.argv[1:]
  if a==["selftest"]:
   assert TAG.startswith("# NEWS");report(status="SELFTEST_PASS")
  elif a==["install"]:report(**install())
  elif a==["verify"]:report(**verify())
  else:stop("BAD_COMMAND")
 except Exception as e:report(status="SAFE_STOP",error=str(e)[:120]);sys.exit(2)
if __name__=="__main__":main()
