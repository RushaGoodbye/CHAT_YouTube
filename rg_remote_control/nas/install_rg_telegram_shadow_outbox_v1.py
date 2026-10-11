#!/usr/bin/env python3
"""Safe local NAS shadow outbox install. Two pinned scripts, selftests, backups.
Never sends Telegram, reads or changes Cloudflare, or toggles live delivery.
"""
import datetime,json,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
SCRIPTS=[
 ("rg_telegram_local_review_decision_v1.py","5dda3f0c1bae844acc76fee505326f985bf7a972"),
 ("rg_telegram_nas_delivery_shadow_outbox_v1.py","c826211f5f5f556511f194110fd286d5e422c7b5")
]
HOOK_MARK="# RG_NAS_DELIVERY_SHADOW_OUTBOX_V1"
ANCHORS=("# RG_NAS_SHADOW_RUNTIME_V1_END",'AUTODEPLOY="$ROOT/RG_NAS_AUTO_DEPLOY.sh"',"# RG_NAS_SHADOW_RUNTIME_V1_BEGIN")
HOOK='''# RG_NAS_DELIVERY_SHADOW_OUTBOX_V1
# Never sends. Stages only approved shadow posts; cross-system gate remains closed.
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_delivery_shadow_outbox_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_delivery_shadow_outbox_v1.py" stage >> "$ROOT/RG_TELEGRAM_STATE/local_delivery_shadow.log" 2>&1 || true
fi
'''
def scheduler_patch(current):
 if HOOK_MARK in current:return current,"ALREADY_INSTALLED"
 anchor=next((k for k in ANCHORS if current.count(k)==1),None)
 if not anchor:return current,"UNKNOWN_LAYOUT"
 return current.replace(anchor,HOOK+"\n"+anchor,1),"PATCHED"
def test_scheduler():
 for marker in ANCHORS:
  base="#!/bin/sh\nROOT=/volume1/docker\n"+marker+"\nexit 0\n"
  once,result=scheduler_patch(base)
  assert result=="PATCHED" and HOOK_MARK in once
  twice,result=scheduler_patch(once)
  assert result=="ALREADY_INSTALLED" and twice==once
 assert scheduler_patch("#!/bin/sh\nexit 0\n")[1]=="UNKNOWN_LAYOUT"
 return "PASS"
def run(args):
 r=subprocess.run(args,text=True,capture_output=True,timeout=25)
 if r.returncode:raise RuntimeError("test_failed:"+pathlib.Path(args[1]).name+":"+((r.stderr or r.stdout)[-350:]))
 return r.stdout.strip()
def fetch(name,sha):
 url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/"+sha+"/rg_remote_control/nas/"+name
 request=urllib.request.Request(url,headers={"User-Agent":"RG-NAS-Shadow-Outbox-Install"})
 with urllib.request.urlopen(request,timeout=25) as response:
  if response.status!=200:raise RuntimeError("source_http_not_ok")
  b=response.read(140001)
 if not b.startswith(b"#!/usr/bin/env python3") or len(b)>140000:raise RuntimeError("invalid_source")
 return b
def main():
 if len(sys.argv)>1 and sys.argv[1]=="selftest":
  print(json.dumps({"status":"INSTALLER_SELFTEST_PASS","scheduler":test_scheduler(),"telegram_sends":0}));return
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 if not (STATE/"migration_shadow.sqlite3").is_file():raise RuntimeError("sqlite_missing")
 if not (STATE/"rg_telegram_nas_event_intake_v1.py").is_file():raise RuntimeError("event_intake_missing")
 if SCHED.is_symlink() or not SCHED.is_file():raise RuntimeError("scheduler_missing")
 if test_scheduler()!="PASS":raise RuntimeError("scheduler_selftest")
 current=SCHED.read_text("utf-8")
 patched,schedule_mode=scheduler_patch(current)
 result=subprocess.run(["/bin/sh","-n"],text=True,input=patched,capture_output=True,timeout=10)
 if result.returncode:raise RuntimeError("scheduler_syntax")
 with tempfile.TemporaryDirectory(prefix="rg-outbox-stage-") as temp:
  staging=pathlib.Path(temp)
  shutil.copy2(STATE/"rg_telegram_nas_event_intake_v1.py",staging/"rg_telegram_nas_event_intake_v1.py")
  checks=[]
  for name,sha in SCRIPTS:(staging/name).write_bytes(fetch(name,sha))
  for name,sha in SCRIPTS:
   script=staging/name
   run([sys.executable,"-m","py_compile",str(script)])
   checks.append({"module":name,"result":run([sys.executable,str(script),"selftest"])})
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  for name,sha in SCRIPTS:
   dest=STATE/name
   if dest.exists():shutil.copy2(dest,STATE/(name+"."+stamp+".bak"))
   fd,newname=tempfile.mkstemp(prefix=".rg-outbox-",dir=str(STATE))
   try:
    with os.fdopen(fd,"wb") as out:out.write((staging/name).read_bytes())
    os.chmod(newname,0o640)
    os.replace(newname,dest)
   finally:
    if os.path.exists(newname):os.unlink(newname)
  if patched!=current:
   shutil.copy2(SCHED,SCHED.with_name(SCHED.name+".outbox-backup-"+stamp))
   fd,newname=tempfile.mkstemp(prefix=".rg-outbox-scheduler-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w") as out:out.write(patched)
    shutil.copymode(SCHED,newname)
    os.replace(newname,SCHED)
   finally:
    if os.path.exists(newname):os.unlink(newname)
  print(json.dumps({"status":"LOCAL_SHADOW_OUTBOX_INSTALLED","selftests":"PASS","tests":checks,
   "scheduler":schedule_mode,"telegram_sends":0,"cloudflare_calls":0},ensure_ascii=False))
  script=STATE/SCRIPTS[1][0]
  print(run([sys.executable,str(script),"stage"]))
  print(run([sys.executable,str(script),"status"]))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","reason":type(e).__name__+":"+str(e)[:300],"telegram_sends":0},ensure_ascii=False),file=sys.stderr)
  sys.exit(1)
