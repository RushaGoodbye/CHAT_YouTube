#!/usr/bin/env python3
"""Install dormant native Telegram hook to existing NAS scheduler, preserving crons.
Never creates cutover marker, never starts polling, never sends a message.
"""
import argparse,datetime,fcntl,json,os,pathlib,shutil,subprocess,sys,tempfile
ROOT=pathlib.Path("/volume1/docker")
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
STATE=ROOT/"RG_TELEGRAM_STATE"
GATE=ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled"
BOT=STATE/"rg_telegram_nas_native_bot_v01.py"
MARK="# RG_NAS_NATIVE_TELEGRAM_BOT_V01"
ANCHORS=("# RG_NAS_SHADOW_RUNTIME_V1_END","# RG_NAS_LOCAL_REVIEW_EXPORT_V1","AUTODEPLOY=")
HOOK='''# RG_NAS_NATIVE_TELEGRAM_BOT_V01
# Polling is OFF until a separately verified cutover gate is installed.
# Never add an unverified gate. This module has an exclusive poll lock.
if [ -f "$ROOT/RG_SECRETS/rg_nas_telegram_cutover_enabled" ] &&
   [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_native_bot_v01.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_native_bot_v01.py" once >> "$ROOT/RG_TELEGRAM_STATE/native_bot.log" 2>&1 || true
fi
'''
def out(status,**kw):
 print(json.dumps({"status":status,"telegram_sends":0,"telegram_polls":0,"cloudflare_calls":0,**kw},ensure_ascii=False))
def patch(text):
 count=text.count(MARK)
 if count==1:return text,"ALREADY_PRESENT","existing"
 if count>1:raise RuntimeError("duplicated_native_hook")
 anchor=next((a for a in ANCHORS if text.count(a)==1),None)
 if anchor is None:raise RuntimeError("no_unique_safe_scheduler_anchor")
 result=text.replace(anchor,HOOK+"\n"+anchor,1)
 return result,"PATCHED",anchor
def test_syntax(text):
 p=subprocess.run(["/bin/sh","-n"],input=text,text=True,capture_output=True,timeout=6)
 if p.returncode:raise RuntimeError("scheduler_syntax_rejected")
def selftest():
 for anchor in ANCHORS:
  text='#!/bin/sh\nROOT="/volume1/docker"\n'+anchor+'\nexit 0\n'
  after,mode,found=patch(text)
  assert mode=="PATCHED" and found==anchor and after.count(MARK)==1
  assert patch(after)==(after,"ALREADY_PRESENT","existing")
  test_syntax(after)
 try:patch('#!/bin/sh\nexit 0\n')
 except RuntimeError:pass
 else:raise AssertionError("unsafe_unknown_layout_accepted")
 assert MARK in HOOK and "rg_nas_telegram_cutover_enabled" in HOOK
 out("NATIVE_SCHEDULER_HOOK_SELFTEST_PASS",legacy_layout_fallbacks="PASS",no_send="PASS")
def install():
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 if SCHED.is_symlink() or not SCHED.is_file():raise RuntimeError("scheduler_missing")
 if BOT.is_symlink() or not BOT.is_file():raise RuntimeError("native_bot_not_installed")
 if GATE.exists() or GATE.is_symlink():raise RuntimeError("cutover_gate_must_be_absent")
 with (STATE/".native_scheduler_patch.lock").open("a+") as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  before=SCHED.read_text("utf-8")
  after,mode,anchor=patch(before)
  test_syntax(after)
  if mode=="ALREADY_PRESENT":
   out("NATIVE_SCHEDULER_HOOK_READY",scheduler=mode,gate="CLOSED",
       file_changed=False,no_telegram_polling=True);return
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  backup=SCHED.with_name(SCHED.name+".native-gated-"+stamp+".bak")
  shutil.copy2(SCHED,backup)
  fd,tmpfile=tempfile.mkstemp(prefix=".rg-native-hook-",dir=str(SCHED.parent))
  try:
   with os.fdopen(fd,"w",encoding="utf-8") as w:w.write(after)
   shutil.copymode(SCHED,tmpfile)
   os.replace(tmpfile,SCHED)
  finally:
   if os.path.exists(tmpfile):os.unlink(tmpfile)
  fresh=SCHED.read_text("utf-8")
  test_syntax(fresh)
  if fresh.count(MARK)!=1:raise RuntimeError("postinstall_hook_missing")
  out("NATIVE_SCHEDULER_HOOK_READY",scheduler=mode,anchor=anchor,
      backup_created=True,gate="CLOSED",no_telegram_polling=True,
      no_telegram_sends=True,backup_file=backup.name)
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","install"));a=p.parse_args()
 if a.mode=="selftest":selftest()
 else:install()
if __name__=="__main__":
 try:main()
 except Exception as e:
  out("BLOCKED",reason=type(e).__name__+":"+str(e)[:110],production_delivery_enabled=False)
  sys.exit(1)
