#!/usr/bin/env python3
"""Install dormant selective Cloudflare->NAS moderation toolkit in Synology:
legacy scanner guard, isolated Telegram update handoff, minute silence dedupe,
and scheduler activation after 20-minute Cloudflare propagation.
No Cloudflare write, no Telegram poll/send during installation.
"""
import argparse,datetime,json,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SECRETS=ROOT/"RG_SECRETS"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
GATE=SECRETS/"rg_nas_telegram_cutover_enabled"
PAUSE=SECRETS/"rg_cloudflare_migration_pause"
FREEZE=SECRETS/"rg_cf_moderation_handoff_freeze"
SOURCES={
 "rg_telegram_nas_minute_silence_v1.py":"3234bf880d516b613b3bd62db38ab8cfcaad51b0",
 "rg_telegram_cf_selective_scanner_stop_v1.py":"830a0278c0c4ba66466b3965c0fe19964d3426cb",
 "rg_telegram_cf_selective_moderation_handoff_v1.py":"d19060cc2cc2dba545b91cd4feb23b880201a65a",
 "rg_telegram_nas_selective_moderation_activate_v1.py":"60f887f02e80bb190bcea391ee7b38285a29ecd0"
}
ANCHOR="# RG_NAS_NATIVE_TELEGRAM_BOT_V01"
HOOK_MARK="# RG_NAS_SELECTIVE_MODERATION_AUTOCUTOVER_V1"
HOOK='''# RG_NAS_SELECTIVE_MODERATION_AUTOCUTOVER_V1
# Old Cloudflare scanner must be stopped, old getUpdates owner verified NAS.
# Kyiv alerts, moment of silence, holidays and daily Content Hub still on CF.
if [ -f "$ROOT/RG_SECRETS/rg_cf_moderation_handoff_freeze" ] &&
   [ -f "$ROOT/RG_TELEGRAM_STATE/rg_cf_moderation_handoff_v1/deployed.json" ] &&
   [ ! -f "$ROOT/RG_SECRETS/rg_nas_telegram_cutover_enabled" ] &&
   [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_selective_moderation_activate_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_selective_moderation_activate_v1.py" activate >> "$ROOT/RG_TELEGRAM_STATE/nas_selective_activation.log" 2>&1 || true
fi
'''
def out(status,**k):print(json.dumps({"status":status,"telegram_sends":0,
 "telegram_polls":0,"cloudflare_writes":0,"nas_gate_opened":False,**k},ensure_ascii=False),flush=True)
def syntax(body):
 p=subprocess.run(["/bin/sh","-n"],input=body,text=True,capture_output=True,timeout=5)
 if p.returncode:raise RuntimeError("SCHEDULER_SHELL_SYNTAX_INVALID")
def patch(body):
 if body.count(HOOK_MARK)==1:return body,"ALREADY_INSTALLED"
 if body.count(HOOK_MARK)>1:raise RuntimeError("HOOK_DUPLICATED")
 if body.count(ANCHOR)!=1:raise RuntimeError("NATIVE_SCHEDULER_ANCHOR_NOT_UNIQUE")
 return body.replace(ANCHOR,HOOK+"\n"+ANCHOR,1),"PATCHED"
def selftest():
 s='#!/bin/sh\nROOT="/volume1/docker"\n'+ANCHOR+'\nexit 0\n'
 a,mode=patch(s)
 assert mode=="PATCHED" and patch(a)==(a,"ALREADY_INSTALLED")
 assert a.count(HOOK_MARK)==1
 syntax(a)
 out("RG_NAS_SELECTIVE_TOOLKIT_SELFTEST_PASS",live_stays_off=True,kyiv_alerts_preserved=True)
def fetch(name,pin):
 url=f"https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/{pin}/rg_remote_control/nas/{name}"
 req=urllib.request.Request(url,headers={"User-Agent":"RG-Selective-Migration/1"})
 with urllib.request.urlopen(req,timeout=20) as r:raw=r.read(30000)
 if not raw.startswith(b"#!/usr/bin/env python3") or not 3500<=len(raw)<=30000:
  raise RuntimeError("MODULE_DOWNLOAD_INVALID")
 return raw
def install():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if GATE.exists() or PAUSE.exists() or FREEZE.exists():
  raise RuntimeError("MIGRATION_ALREADY_ACTIVE")
 if SCHED.is_symlink() or not SCHED.is_file():raise RuntimeError("NAS_SCHEDULER_MISSING")
 if not (STATE/"rg_telegram_nas_native_bot_v01.py").is_file():
  raise RuntimeError("NATIVE_BOT_NOT_INSTALLED")
 if not (STATE/"cf_moderation_handoff_stage_v1/scanner_worker.js").is_file():
  raise RuntimeError("SCANNER_GUARD_SOURCE_NOT_STAGED")
 before=SCHED.read_text("utf-8");after,mode=patch(before);syntax(after)
 with tempfile.TemporaryDirectory(prefix="rg-selective-toolkit-") as tmp:
  root=pathlib.Path(tmp)
  for name,pin in SOURCES.items():
   f=root/name
   f.write_bytes(fetch(name,pin))
   for stage,cmd in (("COMPILE",[sys.executable,"-m","py_compile",str(f)]),
      ("SELFTEST",[sys.executable,str(f),"selftest"])):
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=18)
    if p.returncode:
     last=" | ".join((p.stderr or p.stdout or "").strip().splitlines()[-3:])[:180]
     raise RuntimeError("MODULE_"+stage+"_FAILED_"+name+":"+last)
    if stage=="SELFTEST":
     result=json.loads(p.stdout)
     if not any("PASS" in str(v) for v in result.values()):
      raise RuntimeError("MODULE_SELFTEST_UNEXPECTED_"+name)
     out("SELECTIVE_COMPONENT_PASS",component=name)
  now=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  for name in SOURCES:
   target=STATE/name
   if target.is_symlink():raise RuntimeError("SYMLINK_TARGET_REFUSED")
   if target.is_file():shutil.copy2(target,STATE/(name+"."+now+".bak"))
   fd,path=tempfile.mkstemp(prefix=".rg-selective-",dir=str(STATE))
   try:
    with os.fdopen(fd,"wb") as f:f.write((root/name).read_bytes())
    os.chmod(path,0o640);os.replace(path,target)
   finally:
    if os.path.exists(path):os.unlink(path)
  if mode=="PATCHED":
   backup=SCHED.with_name(SCHED.name+".selective-"+now+".bak")
   shutil.copy2(SCHED,backup)
   fd,path=tempfile.mkstemp(prefix=".rg-selective-scheduler-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(after)
    shutil.copymode(SCHED,path);os.replace(path,SCHED)
   finally:
    if os.path.exists(path):os.unlink(path)
  syntax(SCHED.read_text("utf-8"))
  out("RG_NAS_SELECTIVE_TOOLKIT_READY",modules=len(SOURCES),
   scheduler=mode,all_cloudflare_crons_unchanged=True,
   next_step="preflight_then_pause_only_legacy_scanner")
if __name__=="__main__":
 try:
  arg=argparse.ArgumentParser();arg.add_argument("mode",choices=("selftest","install"))
  a=arg.parse_args().mode
  if a=="selftest":selftest()
  else:install()
 except Exception as e:
  msg=str(e)
  if len(msg)>150:msg=type(e).__name__
  out("BLOCKED",reason=msg)
  sys.exit(1)
