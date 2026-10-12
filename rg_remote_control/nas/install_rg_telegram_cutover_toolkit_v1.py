#!/usr/bin/env python3
"""Install verified reversible CF->NAS cutover toolkit in Synology scheduler.
Installation never changes CF Cron, opens the NAS bot, polls, or sends Telegram.
"""
import argparse,datetime,json,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
FILES={
 "rg_telegram_cf_cron_pause_v1.py":"66d4b2ad416ca7640fe4b75e85e86fbf5ba83e14",
 "rg_telegram_cf_scanner_guard_deploy_v1.py":"05e2dc05e3f2dd3bad67d804fab27bf85006061d",
 "rg_telegram_nas_one_writer_activate_v1.py":"38f6d7a750667fe77e7b7ab7aaa28ef298f14e16"
}
SCHED_MARK="# RG_NAS_AUTOCUTOVER_V1"
AN="# RG_NAS_NATIVE_TELEGRAM_BOT_V01"
HOOK='''# RG_NAS_AUTOCUTOVER_V1
# Wait for both remote DO owner and all three Cron schedules + propagation.
if [ -f "$ROOT/RG_SECRETS/rg_cloudflare_migration_pause" ] &&
   [ ! -f "$ROOT/RG_SECRETS/rg_nas_telegram_cutover_enabled" ] &&
   [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_one_writer_activate_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_one_writer_activate_v1.py" activate >> "$ROOT/RG_TELEGRAM_STATE/nas_cutover_activation.log" 2>&1 || true
fi
# RG_NAS_CUTOVER_WATCHDOG_V1
# If NAS takeover never completes, restore old CF cron schedules after 45 min.
if [ -f "$ROOT/RG_SECRETS/rg_cloudflare_migration_pause" ] &&
   [ ! -f "$ROOT/RG_SECRETS/rg_nas_telegram_cutover_enabled" ] &&
   [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_cf_cron_pause_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_cf_cron_pause_v1.py" watchdog >> "$ROOT/RG_TELEGRAM_STATE/nas_cutover_watchdog.log" 2>&1 || true
fi
'''
def out(status,**props):
 print(json.dumps({"status":status,"telegram_sends":0,"telegram_polls":0,
  "cloudflare_writes":0,"gate_opened":False,**props},ensure_ascii=False),flush=True)
def patch(body):
 if body.count(SCHED_MARK)==1:return body,"ALREADY_READY"
 if body.count(SCHED_MARK)>1:raise RuntimeError("AUTOCUTOVER_DUPLICATE_HOOK")
 if body.count(AN)!=1:raise RuntimeError("NATIVE_SCHEDULER_MARK_MISSING")
 return body.replace(AN,HOOK+"\n"+AN,1),"PATCHED"
def syntax(body):
 result=subprocess.run(["/bin/sh","-n"],input=body,text=True,capture_output=True,timeout=5)
 if result.returncode:raise RuntimeError("SCHEDULER_SYNTAX_FAILED")
def selftest():
 sample='#!/bin/sh\nROOT="/volume1/docker"\n'+AN+'\nexit 0\n'
 modified,mode=patch(sample)
 assert mode=="PATCHED"
 assert patch(modified)==(modified,"ALREADY_READY")
 assert modified.count("# RG_NAS_CUTOVER_WATCHDOG_V1")==1
 syntax(modified)
 out("RG_CUTOVER_TOOLKIT_SELFTEST_PASS",cron_pause_reversible=True,auto_activation=True,auto_rollback=True)
def fetch(name,pin):
 url=f"https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/{pin}/rg_remote_control/nas/{name}"
 req=urllib.request.Request(url,headers={"User-Agent":"RG-NAS-Cutover-Toolkit/1"})
 with urllib.request.urlopen(req,timeout=18) as resp:data=resp.read(40000)
 if not data.startswith(b"#!/usr/bin/env python3") or not 5000<len(data)<40000:
  raise RuntimeError("CUTOVER_SOURCE_INVALID")
 return data
def install():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if (ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled").exists() or (ROOT/"RG_SECRETS/rg_cloudflare_migration_pause").exists():
  raise RuntimeError("MIGRATION_ALREADY_STARTED")
 if not SCHED.is_file() or SCHED.is_symlink():raise RuntimeError("SCHEDULER_MISSING")
 for name in ("rg_telegram_nas_native_bot_v01.py","rg_telegram_nas_minute_silence_v1.py"):
  if not (STATE/name).is_file():raise RuntimeError("NATIVE_RUNTIME_MISSING")
 before=SCHED.read_text("utf-8");after,mode=patch(before);syntax(after)
 with tempfile.TemporaryDirectory(prefix="rg-cutover-kit-") as work:
  work=pathlib.Path(work)
  for name,pin in FILES.items():
   path=work/name;path.write_bytes(fetch(name,pin))
   p=subprocess.run([sys.executable,"-m","py_compile",str(path)],capture_output=True,text=True,timeout=8)
   if p.returncode:raise RuntimeError("SOURCE_PY_COMPILE_FAILED_"+name)
   p=subprocess.run([sys.executable,str(path),"selftest"],capture_output=True,text=True,timeout=10)
   if p.returncode:raise RuntimeError("SOURCE_SELFTEST_FAILED_"+name)
   parsed=json.loads(p.stdout)
   if "PASS" not in (parsed.get("status") or ""):raise RuntimeError("SOURCE_SELFTEST_RESULT_INVALID_"+name)
   out("CUTOVER_COMPONENT_TEST_PASS",component=name,result=parsed["status"])
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  for name in FILES:
   dst=STATE/name
   if dst.is_symlink():raise RuntimeError("CUTOVER_DEST_SYMLINK")
   if dst.exists():shutil.copy2(dst,STATE/(name+"."+stamp+".bak"))
   fd,tmp=tempfile.mkstemp(prefix=".rg-ct-install-",dir=str(STATE))
   try:
    with os.fdopen(fd,"wb") as w:w.write((work/name).read_bytes())
    os.chmod(tmp,0o640);os.replace(tmp,dst)
   finally:
    if os.path.exists(tmp):os.unlink(tmp)
  if mode=="PATCHED":
   shutil.copy2(SCHED,SCHED.with_name(SCHED.name+".cutover-"+stamp+".bak"))
   fd,tmp=tempfile.mkstemp(prefix=".rg-ct-scheduler-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w",encoding="utf-8") as w:w.write(after)
    shutil.copymode(SCHED,tmp);os.replace(tmp,SCHED)
   finally:
    if os.path.exists(tmp):os.unlink(tmp)
  syntax(SCHED.read_text("utf-8"))
  out("RG_NAS_CUTOVER_TOOLKIT_READY",scheduler=mode,components=len(FILES),
      no_live_process_stopped=True,no_live_process_started=True,
      next_step="run_cf_pause_then_scanner_guard_deploy")
if __name__=="__main__":
 try:
  p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","install"))
  a=p.parse_args()
  if a.mode=="selftest":selftest()
  else:install()
 except Exception as ex:
  reason=str(ex)
  if not (len(reason)<130 and all(c.isupper() or c.isdigit() or c in "_-." for c in reason)):
   reason=type(ex).__name__
  out("BLOCKED",reason=reason)
  sys.exit(1)
