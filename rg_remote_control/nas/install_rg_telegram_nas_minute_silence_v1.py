#!/usr/bin/env python3
"""Install dormant minute-silence publisher and gated scheduler hook on NAS.
Only once windows 09:00-09:05 and only after external verified cutover gate.
No message, poll, CF write, or cron update in install mode.
"""
import argparse,datetime,json,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE";SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
DST=STATE/"rg_telegram_nas_minute_silence_v1.py"
PIN="03b817df31947e82b9003c052ac46e6de71abd80"
URL="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/"+PIN+"/rg_remote_control/nas/"+DST.name
GATE=ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled"
MARK="# RG_NAS_MINUTE_SILENCE_V1"
HOOK='''# RG_NAS_MINUTE_SILENCE_V1
# Exact 09:00..09:05 Europe/Kyiv with canonical PNG, single-attempt durable journal.
if [ -f "$ROOT/RG_SECRETS/rg_nas_telegram_cutover_enabled" ] &&
   [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_minute_silence_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_minute_silence_v1.py" once >> "$ROOT/RG_TELEGRAM_STATE/nas_minute_silence.log" 2>&1 || true
fi
'''
ANCHORS=("# RG_NAS_NATIVE_TELEGRAM_BOT_V01","# RG_NAS_LOCAL_REVIEW_EXPORT_V1","AUTODEPLOY=")
def out(status,**fields):
 print(json.dumps({"status":status,"telegram_sends":0,"telegram_polls":0,"cloudflare_writes":0,**fields},ensure_ascii=False),flush=True)
def patch(body):
 if body.count(MARK)==1:return body,"ALREADY_INSTALLED"
 if body.count(MARK)>1:raise RuntimeError("duplicate_hook")
 a=next((m for m in ANCHORS if body.count(m)==1),None)
 if not a:raise RuntimeError("scheduler_layout_unknown")
 return body.replace(a,HOOK+"\n"+a,1),"PATCHED"
def check(body):
 p=subprocess.run(["/bin/sh","-n"],input=body,text=True,capture_output=True,timeout=5)
 if p.returncode:raise RuntimeError("scheduler_syntax_invalid")
def selftest():
 for a in ANCHORS:
  original='#!/bin/sh\nROOT="/volume1/docker"\n'+a+'\nexit 0\n'
  new,status=patch(original)
  assert status=="PATCHED" and new.count(MARK)==1 and patch(new)==(new,"ALREADY_INSTALLED")
  check(new)
 out("NAS_MINUTE_INSTALL_SELFTEST_PASS",cutover_gate="CLOSED",network_calls=0)
def main():
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 if GATE.exists():raise RuntimeError("cutover_gate_must_be_closed")
 if SCHED.is_symlink() or not SCHED.is_file():raise RuntimeError("nas_scheduler_missing")
 before=SCHED.read_text("utf-8");after,state=patch(before);check(after)
 with tempfile.TemporaryDirectory(prefix="rg-minute-install-") as tmp:
  file=pathlib.Path(tmp)/DST.name
  req=urllib.request.Request(URL,headers={"User-Agent":"RG-NAS-Minute/1"})
  with urllib.request.urlopen(req,timeout=20) as resp:
   raw=resp.read(40000)
  if not raw.startswith(b"#!/usr/bin/env python3") or not 4000<len(raw)<40000:
   raise RuntimeError("source_validation_failed")
  file.write_bytes(raw)
  for args in ([sys.executable,"-m","py_compile",str(file)],
                [sys.executable,str(file),"selftest"]):
   p=subprocess.run(args,text=True,capture_output=True,timeout=16)
   if p.returncode:raise RuntimeError("offline_module_validation_failed")
   if args[-1]=="selftest":out("NAS_MINUTE_MODULE_TEST_PASS",selftest=p.stdout.strip())
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  if DST.is_symlink():raise RuntimeError("dest_symlink")
  if DST.exists():shutil.copy2(DST,STATE/(DST.name+"."+stamp+".bak"))
  fd,tgt=tempfile.mkstemp(prefix=".rg-minute-",dir=str(STATE))
  try:
   with os.fdopen(fd,"wb") as f:f.write(raw)
   os.chmod(tgt,0o640);os.replace(tgt,DST)
  finally:
   if os.path.exists(tgt):os.unlink(tgt)
  if state=="PATCHED":
   backup=SCHED.with_name(SCHED.name+".minute-"+stamp+".bak")
   shutil.copy2(SCHED,backup)
   fd,tgt=tempfile.mkstemp(prefix=".rg-minute-hook-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(after)
    shutil.copymode(SCHED,tgt);os.replace(tgt,SCHED)
   finally:
    if os.path.exists(tgt):os.unlink(tgt)
  p=subprocess.run([sys.executable,str(DST),"status"],text=True,capture_output=True,timeout=12)
  if p.returncode:raise RuntimeError("new_module_health_failed")
  out("NAS_MINUTE_SILENCE_INSTALLED",scheduler=state,report=json.loads(p.stdout),
      live_delivery_enabled=False,no_message_sent=True)
if __name__=="__main__":
 try:
  mode=argparse.ArgumentParser();mode.add_argument("mode",choices=("selftest","install"))
  a=mode.parse_args()
  if a.mode=="selftest":selftest()
  else:main()
 except Exception as ex:
  out("BLOCKED",reason=type(ex).__name__+":"+str(ex)[:110],live_delivery_enabled=False)
  sys.exit(1)
