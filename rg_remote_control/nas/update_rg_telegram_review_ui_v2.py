#!/usr/bin/env python3
"""RG NAS review UI v2 zero-publishing safe update, atomically with rollback.
Does not touch sqlite, secrets, SSH, Cloudflare, or Telegram API.
"""
import datetime,fcntl,json,os,pathlib,shutil,signal,subprocess,sys,tempfile,time,urllib.error,urllib.request,base64
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SOURCE=STATE/"rg_telegram_local_review_server_v1.py"
PASSWORD=ROOT/"RG_SECRETS/rg_local_review_ui_password"
MARK="RG_NAS_LOCAL_REVIEW_V1"
COMMIT="4bcf2b6f9ef80f4e6c51487cb3728d13f6464649"
URL=("https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/"+COMMIT+
    "/rg_remote_control/nas/rg_telegram_local_review_server_v1.py")
LOG=STATE/"local_review_ui.log"
LOCK=STATE/".local_review_ui_ensure.lock"
def output(status,**kwargs):
 print(json.dumps({"status":status,"telegram_sends":0,"cloudflare_calls":0,**kwargs},ensure_ascii=False),flush=True)
def fetch():
 req=urllib.request.Request(URL,headers={"User-Agent":"RG-Telegram-Review-UI-Updater/2"})
 with urllib.request.urlopen(req,timeout=25) as resp:
  if resp.status!=200:raise RuntimeError("source_http")
  content=resp.read(60001)
 if not content.startswith(b"#!/usr/bin/env python3") or not 15000<len(content)<60000:
  raise RuntimeError("bad_source_size")
 if b'UI_VERSION="2"' not in content or b"api.telegram.org" in content:raise RuntimeError("wrong_release")
 return content
def command(args,timeout=20):
 r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if r.returncode:
  raise RuntimeError("preflight_failed:"+pathlib.Path(args[1]).name+":"+((r.stderr or r.stdout)[-220:]))
 return r.stdout.strip()
def target_pids():
 found=[]
 for proc in pathlib.Path("/proc").iterdir():
  if not proc.name.isdigit():continue
  try:
   argv=[arg.decode("utf-8","replace") for arg in (proc/"cmdline").read_bytes().split(b"\0") if arg]
   if len(argv)>=3 and argv[-1]=="serve" and pathlib.Path(argv[-2])==SOURCE:
    found.append(int(proc.name))
  except (OSError,ValueError):pass
 return found
def health():
 try:
  with urllib.request.urlopen("http://127.0.0.1:8767/health",timeout=2) as req:
   return json.loads(req.read(2000))
 except (OSError,ValueError):return {}
def authenticated():
 if PASSWORD.is_symlink() or not PASSWORD.is_file():return False
 value=PASSWORD.read_text("utf-8").strip()
 if len(value)<32:return False
 token=base64.b64encode(("rg:"+value).encode("utf-8")).decode("ascii")
 req=urllib.request.Request("http://127.0.0.1:8767/",headers={"Authorization":"Basic "+token})
 try:
  with urllib.request.urlopen(req,timeout=3) as rsp:
   rsp.read(64)
   return rsp.status==200
 except urllib.error.HTTPError:return False
def stop():
 current=target_pids()
 if len(current)!=1:raise RuntimeError("unable_to_identify_single_review_process")
 os.kill(current[0],signal.SIGTERM)
 for _ in range(45):
  time.sleep(.2)
  if not health():return
 raise RuntimeError("old_service_did_not_stop")
def start():
 with LOG.open("ab") as log:
  subprocess.Popen([sys.executable,str(SOURCE),"serve"],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,close_fds=True,start_new_session=True)
 for _ in range(45):
  time.sleep(.2)
  data=health()
  if data.get("app")==MARK and data.get("status")=="READY":return data
 raise RuntimeError("new_service_not_ready")
def main():
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 if not SOURCE.is_file() or SOURCE.is_symlink():raise RuntimeError("old_service_source_missing")
 if not health().get("app")==MARK:raise RuntimeError("old_service_not_running")
 STATE.mkdir(parents=True,exist_ok=True)
 payload=fetch()
 with tempfile.TemporaryDirectory(prefix=".rg-review-v2-") as tmp:
  # Use a test copy with only stdlib dependencies; no DB or secrets opened.
  sample=pathlib.Path(tmp)/SOURCE.name
  sample.write_bytes(payload)
  command([sys.executable,"-m","py_compile",str(sample)])
  print(command([sys.executable,str(sample),"selftest"]))
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
 backup=STATE/(SOURCE.name+"."+stamp+".v1.bak")
 shutil.copy2(SOURCE,backup)
 lock_file=LOCK.open("a+")
 with lock_file:
  fcntl.flock(lock_file,fcntl.LOCK_EX)
  stopped=False
  replaced=False
  try:
   if health().get("app")!=MARK:raise RuntimeError("service_changed_during_validation")
   if len(target_pids())!=1:raise RuntimeError("multiple_server_processes")
   stop()
   stopped=True
   fd,tmpname=tempfile.mkstemp(prefix=".rg-review-release-",dir=str(STATE))
   try:
    with os.fdopen(fd,"wb") as dest:dest.write(payload)
    shutil.copymode(SOURCE,tmpname)
    os.replace(tmpname,SOURCE)
   finally:
    if os.path.exists(tmpname):os.unlink(tmpname)
   replaced=True
   result=start()
   if result.get("ui_version")!="2" or not authenticated():raise RuntimeError("ui_v2_health_or_auth_failed")
   output("LOCAL_REVIEW_UI_V2_READY",ui_version="2",auth="PASS",backup=str(backup),browser_url="http://127.0.0.1:18767",existing_password_unchanged=True)
  except Exception as exc:
   if replaced:
    current=target_pids()
    if len(current)==1:
     try:stop()
     except Exception:pass
    shutil.copy2(backup,SOURCE)
   if stopped:
    try:start()
    except Exception:pass
   output("ROLLBACK_ATTEMPTED",reason=type(exc).__name__+":"+str(exc)[:160],old_service_ready=health().get("app")==MARK)
   raise
def selftest():
 assert SOURCE.name=="rg_telegram_local_review_server_v1.py"
 assert MARK=="RG_NAS_LOCAL_REVIEW_V1"
 assert not any(word in URL for word in ("/master/","/main/"))
 output("UPDATER_SELFTEST_PASS",network_calls=0)
if __name__=="__main__":
 try:
  if len(sys.argv)>1 and sys.argv[1]=="selftest":selftest()
  else:selftest();main()
 except Exception as e:
  output("BLOCKED",reason=type(e).__name__+":"+str(e)[:150])
  sys.exit(1)
