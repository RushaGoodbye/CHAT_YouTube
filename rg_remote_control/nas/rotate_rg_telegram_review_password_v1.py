#!/usr/bin/env python3
"""Rotate the exposed RG NAS review UI password, without Telegram/Cloudflare calls.
Requires root, performs offline checks, local loopback restart and auth verification.
Never prints the old or the new password.
"""
import argparse,base64,json,os,pathlib,secrets,signal,stat,subprocess,sys,tempfile,time,urllib.error,urllib.request
ROOT=pathlib.Path("/volume1/docker")
KEY=ROOT/"RG_SECRETS/rg_local_review_ui_password"
SERVER=ROOT/"RG_TELEGRAM_STATE/rg_telegram_local_review_server_v1.py"
HOST="http://127.0.0.1:8767/"
EXPECTED="RG_NAS_LOCAL_REVIEW_V1"
def report(status,**extra):
 print(json.dumps({"status":status,"telegram_sends":0,**extra},ensure_ascii=False),flush=True)
def secure_replace(value):
 if KEY.is_symlink() or not KEY.is_file():raise RuntimeError("password_file_missing_or_symlink")
 fd,name=tempfile.mkstemp(prefix=".rg-new-review-password-",dir=str(KEY.parent))
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,"w",encoding="utf-8") as output:
   output.write(value+"\n")
   output.flush()
   os.fsync(output.fileno())
  os.replace(name,KEY)
 finally:
  if os.path.exists(name):os.unlink(name)
def target_pids():
 results=[]
 for p in pathlib.Path("/proc").iterdir():
  if not p.name.isdigit():continue
  try:
   argv=(p/"cmdline").read_bytes().split(b"\0")
   args=[a.decode("utf-8","replace") for a in argv if a]
   if len(args)>=3 and args[-1]=="serve" and pathlib.Path(args[-2])==SERVER:
    results.append(int(p.name))
  except (OSError,ValueError):continue
 return results
def health():
 try:
  with urllib.request.urlopen(HOST+"health",timeout=1.5) as resp:
   d=json.loads(resp.read(3000))
  return d.get("app")==EXPECTED and d.get("status")=="READY"
 except (OSError,ValueError,urllib.error.URLError):return False
def status_for(secret):
 token=base64.b64encode(("rg:"+secret).encode("utf-8")).decode("ascii")
 request=urllib.request.Request(HOST,headers={"Authorization":"Basic "+token})
 try:
  with urllib.request.urlopen(request,timeout=4) as resp:
   resp.read(128)
   return resp.status
 except urllib.error.HTTPError as err:return err.code
def boot():
 proc=subprocess.run([sys.executable,str(SERVER),"ensure"],capture_output=True,text=True,timeout=18)
 return proc.returncode==0 and health()
def wait_down(pid):
 for _ in range(35):
  if not health():return True
  time.sleep(.2)
 return False
def selftest():
 sample=[["/usr/bin/python3",str(SERVER),"serve"],["/usr/bin/python3","/tmp/no.py","serve"]]
 assert sample[0][-1]=="serve" and pathlib.Path(sample[0][-2])==SERVER
 assert pathlib.Path(sample[1][-2])!=SERVER
 assert KEY.parent==ROOT/"RG_SECRETS"
 report("ROTATION_SELFTEST_PASS",network_calls=0)
def rotate():
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 if SERVER.is_symlink() or not SERVER.is_file():raise RuntimeError("review_server_missing")
 if KEY.is_symlink() or not KEY.is_file():raise RuntimeError("key_missing")
 if not health():raise RuntimeError("review_server_unhealthy")
 pids=target_pids()
 if len(pids)!=1:raise RuntimeError("review_process_not_uniquely_identified")
 previous=KEY.read_text("utf-8").strip()
 if len(previous)<32:raise RuntimeError("old_password_invalid")
 now=secrets.token_urlsafe(48)
 if now==previous:raise RuntimeError("random_key_reused")
 # Change password file first, immediately stop service holding the old secret.
 secure_replace(now)
 os.kill(pids[0],signal.SIGTERM)
 if not wait_down(pids[0]):
  secure_replace(previous)
  raise RuntimeError("review_server_did_not_stop;password_reverted")
 if not boot():
  secure_replace(previous)
  boot()
  raise RuntimeError("restart_failed;password_reverted")
 if status_for(now)!=200 or status_for(previous)!=401:
  # If auth check fails, restore the original key to avoid losing management.
  pids=target_pids()
  if len(pids)==1:os.kill(pids[0],signal.SIGTERM);wait_down(pids[0])
  secure_replace(previous)
  boot()
  raise RuntimeError("auth_verification_failed;password_reverted")
 report("REVIEW_PASSWORD_ROTATED",new_auth="PASS",old_auth="REJECTED",password_file=str(KEY),password_displayed=False,loopback_only=True)
def main():
 p=argparse.ArgumentParser()
 p.add_argument("mode",choices=["selftest","rotate"])
 a=p.parse_args()
 if a.mode=="selftest":selftest()
 else:selftest();rotate()
if __name__=="__main__":
 try:main()
 except Exception as exc:
  report("BLOCKED",reason=(type(exc).__name__+":"+str(exc))[:180])
  sys.exit(1)
