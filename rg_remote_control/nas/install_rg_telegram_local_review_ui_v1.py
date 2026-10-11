#!/usr/bin/env python3
"""Install RG Telegram local password-protected browser moderation UI.
Self-tests first. No Cloudflare/Telegram calls. Service binds 127.0.0.1 only.
"""
import argparse,datetime,json,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
SECRET=ROOT/"RG_SECRETS/rg_local_review_ui_password"
NAME="rg_telegram_local_review_server_v1.py"
REV="178422ddedf03d6bace0d32a46fca6739d567e82"
SOURCE="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/"+REV+"/rg_remote_control/nas/"+NAME
MARK="# RG_NAS_LOCAL_REVIEW_UI_SERVICE_V1"
ANCHORS=("# RG_NAS_SHADOW_RUNTIME_V1_END",'AUTODEPLOY="$ROOT/RG_NAS_AUTO_DEPLOY.sh"',"# RG_NAS_SHADOW_RUNTIME_V1_BEGIN")
HOOK='''# RG_NAS_LOCAL_REVIEW_UI_SERVICE_V1
# Password-authenticated loopback-only UI. Restart after reboot via scheduler.
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_local_review_server_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_local_review_server_v1.py" ensure >> "$ROOT/RG_TELEGRAM_STATE/local_review_ui_scheduler.log" 2>&1 || true
fi
'''
def schedule(current):
 if MARK in current:return current,"EXISTING"
 anchor=next((x for x in ANCHORS if current.count(x)==1),None)
 if anchor is None:return current,"UNKNOWN_LAYOUT"
 return current.replace(anchor,HOOK+"\n"+anchor,1),"PATCHED"
def selftest():
 for anchor in ANCHORS:
  current="#!/bin/sh\n"+anchor+"\nexit 0\n"
  p,state=schedule(current)
  assert state=="PATCHED" and p.count(MARK)==1
  assert schedule(p)==(p,"EXISTING")
 assert schedule("#!/bin/sh\nexit 0\n")[1]=="UNKNOWN_LAYOUT"
 print(json.dumps({"status":"INSTALLER_SELFTEST_PASS","scheduler_idempotent":True,"telegram_sends":0}))
def command(args,timeout=30):
 r=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
 if r.returncode:
  # Source selftests should not contain secrets; keep only last diagnostic lines.
  raise RuntimeError("validation_failed:"+pathlib.Path(args[1]).name+":"+(r.stderr or r.stdout)[-300:])
 return r.stdout.strip()
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",nargs="?",choices=["selftest","install","status"],default="install")
 a=p.parse_args()
 if a.mode=="selftest":selftest();return
 if a.mode=="status":
  target=STATE/NAME
  if target.is_file():print(command([sys.executable,str(target),"status"]))
  else:print(json.dumps({"status":"NOT_INSTALLED","telegram_sends":0}))
  return
 selftest()
 for required in ["rg_telegram_local_review_decision_v1.py","rg_telegram_moderation_projection_v1.py","rg_telegram_nas_event_intake_v1.py"]:
  if not (STATE/required).is_file():raise RuntimeError("dependency_missing:"+required)
 if not (STATE/"migration_shadow.sqlite3").is_file():raise RuntimeError("db_missing")
 if SCHED.is_symlink() or not SCHED.is_file():raise RuntimeError("scheduler_missing")
 current=SCHED.read_text("utf-8")
 patched,sched_result=schedule(current)
 # Unknown scheduler layouts must not block the standalone UI, but warn clearly.
 if subprocess.run(["/bin/sh","-n"],input=patched,text=True,capture_output=True,timeout=10).returncode:
  raise RuntimeError("scheduler_syntax_invalid")
 req=urllib.request.Request(SOURCE,headers={"User-Agent":"RG-Local-Review-Install/1"})
 with urllib.request.urlopen(req,timeout=25) as resp:src=resp.read(150001)
 if len(src)>150000 or not src.startswith(b"#!/usr/bin/env python3"):raise RuntimeError("invalid_source")
 with tempfile.TemporaryDirectory(prefix="rg-review-ui-") as d:
  stage=pathlib.Path(d)
  script=stage/NAME
  script.write_bytes(src)
  command([sys.executable,"-m","py_compile",str(script)])
  test_result=command([sys.executable,str(script),"selftest"])
  stamp=datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
  target=STATE/NAME
  if target.exists():shutil.copy2(target,STATE/(NAME+"."+stamp+".bak"))
  fd,tempname=tempfile.mkstemp(prefix=".rg-review-ui-",dir=str(STATE))
  try:
   with os.fdopen(fd,"wb") as f:f.write(src)
   os.chmod(tempname,0o640)
   os.replace(tempname,target)
  finally:
   if os.path.exists(tempname):os.unlink(tempname)
  if patched!=current:
   shutil.copy2(SCHED,SCHED.with_name(SCHED.name+".review-ui-backup-"+stamp))
   fd,tmp=tempfile.mkstemp(prefix=".rg-review-sched-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w") as f:f.write(patched)
    shutil.copymode(SCHED,tmp)
    os.replace(tmp,SCHED)
   finally:
    if os.path.exists(tmp):os.unlink(tmp)
  running=command([sys.executable,str(target),"ensure"],timeout=20)
  # Never disclose access key. User retrieves it via private SSH session.
  print(test_result)
  print(running)
  print(json.dumps({"status":"LOCAL_REVIEW_UI_INSTALLED","scheduler":sched_result,"password_file":str(SECRET),"browser_url_via_ssh_tunnel":"http://localhost:8767","ssh_tunnel":"ssh -L 8767:127.0.0.1:8767 user@nas","username":"rg","password_printed":False,"telegram_sends":0,"cloudflare_calls":0}))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","reason":type(e).__name__+":"+str(e)[:150],"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
