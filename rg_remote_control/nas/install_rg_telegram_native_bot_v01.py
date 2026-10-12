#!/usr/bin/env python3
"""Install RG native Telegram bot on Synology NAS without cutover or sends.
Pinned revision, offline selftest, WAL snapshot test, backup. Scheduler hook
runs ONLY after a separate verified cutover marker is deliberately installed.
"""
import datetime,hashlib,json,os,pathlib,shutil,sqlite3,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker");STATE=ROOT/"RG_TELEGRAM_STATE"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
SOURCE=STATE/"rg_telegram_nas_native_bot_v01.py"
REVISION="86c812840488e783a82c3c0c0a656e97194f224f"
URL="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/"+REVISION+"/rg_remote_control/nas/"+SOURCE.name
MARK="# RG_NAS_NATIVE_TELEGRAM_BOT_V01"
ANCHOR="# RG_NAS_SHADOW_RUNTIME_V1_END"
HOOK='''# RG_NAS_NATIVE_TELEGRAM_BOT_V01
# IMPORTANT: poll Telegram ONLY after a separate verified Cloudflare cutover.
# Without the cutover marker this section never calls getUpdates or sendPhoto.
if [ -f "$ROOT/RG_SECRETS/rg_nas_telegram_cutover_enabled" ] &&
   [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_native_bot_v01.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_native_bot_v01.py" once >> "$ROOT/RG_TELEGRAM_STATE/native_bot.log" 2>&1 || true
fi
'''
def out(status,**props):
 print(json.dumps({"status":status,"telegram_sends":0,"cloudflare_calls":0,**props},ensure_ascii=False),flush=True)
def patch(text):
 if MARK in text:return text,"ALREADY_INSTALLED"
 if text.count(ANCHOR)!=1:raise RuntimeError("scheduler_anchor_missing")
 return text.replace(ANCHOR,HOOK+ANCHOR,1),"PATCHED"
def cmd(args,seconds=22):
 p=subprocess.run(args,text=True,capture_output=True,timeout=seconds)
 if p.returncode:raise RuntimeError("preflight_failed:"+((p.stderr or p.stdout)[-420:]))
 return p.stdout.strip()
def selftest():
 sample='#!/bin/sh\nROOT="/volume1/docker"\n'+ANCHOR+'\nexit 0\n'
 patched,status=patch(sample)
 assert status=="PATCHED" and patch(patched)==(patched,"ALREADY_INSTALLED")
 assert "rg_nas_telegram_cutover_enabled" in patched
 assert cmd(["/bin/sh","-n"])==""
 out("NATIVE_BOT_INSTALLER_SELFTEST_PASS",scheduler_gate="CLOSED_BY_DEFAULT",network_calls=0)
def main():
 if len(sys.argv)>1 and sys.argv[1]=="selftest":selftest();return
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 if not SCHED.is_file() or SCHED.is_symlink():raise RuntimeError("scheduler_missing")
 if not (STATE/"migration_shadow.sqlite3").is_file():raise RuntimeError("existing_local_shadow_missing")
 if not (ROOT/"RG_SECRETS/rg_telegram_bot_token").is_file():raise RuntimeError("telegram_token_not_available")
 if (ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled").exists():
  raise RuntimeError("cutover_gate_already_open_refusing_unverified_reinstall")
 req=urllib.request.Request(URL,headers={"User-Agent":"RG-Native-Bot-Installer/0.1"})
 with urllib.request.urlopen(req,timeout=25) as response:
  if response.status!=200:raise RuntimeError("source_http_error")
  data=response.read(60001)
 if not data.startswith(b"#!/usr/bin/env python3") or not 15000<len(data)<60000:raise RuntimeError("source_size_invalid")
 if b"getUpdates" not in data or b"cloudflare_cutover_not_authorized" not in data:raise RuntimeError("unexpected_source")
 before=SCHED.read_text("utf-8");after,mode=patch(before)
 cmd(["/bin/sh","-n"]) # next call checks actual content via subprocess input
 chk=subprocess.run(["/bin/sh","-n"],text=True,input=after,capture_output=True,timeout=8)
 if chk.returncode:raise RuntimeError("scheduler_syntax_invalid")
 with tempfile.TemporaryDirectory(prefix="rg-native-bot-preflight-") as tmp:
  folder=pathlib.Path(tmp)
  script=folder/SOURCE.name;script.write_bytes(data)
  cmd([sys.executable,"-m","py_compile",str(script)])
  tests=cmd([sys.executable,str(script),"selftest"])
  snapshot=folder/"local-shadow-copy.sqlite3"
  with sqlite3.connect(str(STATE/"migration_shadow.sqlite3"),timeout=12) as live:
   with sqlite3.connect(str(snapshot),timeout=12) as copy:live.backup(copy)
  shadow_copy=folder/"native-bot-test.sqlite3"
  result=cmd([sys.executable,str(script),"status","--db",str(shadow_copy)])
  proof=json.loads(result)
  if proof.get("status")!="NATIVE_BOT_SHADOW_READY" or proof.get("telegram_sends")!=0:
   raise RuntimeError("native_shadow_state_invalid")
  out("NAS_NATIVE_BOT_SNAPSHOT_PASS",selftest=tests,
      shadow=proof,production_database_writes=0,live_telegram_polls=0)
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  if SOURCE.is_symlink():raise RuntimeError("script_symlink_refused")
  if SOURCE.exists():shutil.copy2(SOURCE,STATE/(SOURCE.name+"."+stamp+".bak"))
  fd,tmpfile=tempfile.mkstemp(prefix=".rg-native-",dir=str(STATE))
  try:
   with os.fdopen(fd,"wb") as output:output.write(data)
   os.chmod(tmpfile,0o640);os.replace(tmpfile,SOURCE)
  finally:
   if os.path.exists(tmpfile):os.unlink(tmpfile)
  if mode=="PATCHED":
   shutil.copy2(SCHED,SCHED.with_name(SCHED.name+".native-backup-"+stamp))
   fd,tmpfile=tempfile.mkstemp(prefix=".rg-native-scheduler-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w") as output:output.write(after)
    shutil.copymode(SCHED,tmpfile);os.replace(tmpfile,SCHED)
   finally:
    if os.path.exists(tmpfile):os.unlink(tmpfile)
  current=cmd([sys.executable,str(SOURCE),"status"])
  out("RG_NAS_NATIVE_TELEGRAM_BOT_INSTALLED",bot_status=json.loads(current),
      scheduler=mode,telegram_polls=0,live_delivery_enabled=False,
      next_step="disable_old_Cloudflare_moderation_polling_then_controlled_cutover")
if __name__=="__main__":
 try:main()
 except Exception as e:
  out("BLOCKED",reason=type(e).__name__+":"+str(e)[:180],live_delivery_enabled=False)
  sys.exit(1)
