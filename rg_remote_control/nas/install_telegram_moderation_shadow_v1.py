#!/usr/bin/env python3
"""RG Telegram NAS moderation projection deploy. Additive and shadow-only."""
import pathlib,subprocess,shutil,os,tempfile,datetime,json,sys
R=pathlib.Path("/volume1/docker")
ST=R/"RG_TELEGRAM_STATE"
SCHED=R/"RG_NAS_SCHEDULER_TICK.sh"
MOD=ST/"rg_telegram_moderation_projection_v1.py"
SOURCE=pathlib.Path("/tmp/rg_telegram_moderation_projection_v1.py")
ANCHOR='AUTODEPLOY="$ROOT/RG_NAS_AUTO_DEPLOY.sh"'
HOOK='''# RG_MODERATION_SHADOW_PROJECTION_V1
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_moderation_projection_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_moderation_projection_v1.py" once >> "$ROOT/RG_TELEGRAM_STATE/moderation_shadow.log" 2>&1 || true
fi
'''
def call(cmd):
 x=subprocess.run(cmd,capture_output=True,text=True,timeout=50)
 if x.returncode:raise RuntimeError("Failed: "+cmd[-1]+" "+x.stderr[:150])
 return x.stdout
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ("audit","install"):raise SystemExit("audit|install")
 if not SOURCE.is_file() or not SCHED.is_file() or not (ST/"migration_shadow.sqlite3").is_file():raise SystemExit("BLOCKED: source/scheduler/db missing")
 call([sys.executable,"-m","py_compile",str(SOURCE)])
 call([sys.executable,str(SOURCE),"selftest"])
 current=SCHED.read_text("utf-8")
 if "RG_MODERATION_SHADOW_PROJECTION_V1" not in current and current.count(ANCHOR)!=1:raise SystemExit("BLOCKED: scheduler anchor")
 patched=current if "RG_MODERATION_SHADOW_PROJECTION_V1" in current else current.replace(ANCHOR,HOOK+"\n"+ANCHOR)
 v=subprocess.run(["/bin/sh","-n"],input=patched,text=True,capture_output=True)
 if v.returncode:raise SystemExit("BLOCKED: shell syntax")
 if sys.argv[1]=="audit":
  print(json.dumps({"status":"READY_TO_INSTALL","shadow_only":True,"already_scheduled":current==patched}));return
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
 backups=[]
 try:
  for original in (MOD,SCHED):
   if original.exists():
    backup=original.with_name(original.name+".backup-"+stamp)
    shutil.copy2(original,backup);backups.append((original,backup))
  shutil.copy2(SOURCE,MOD)
  call([sys.executable,str(MOD),"initialize"])
  if current!=patched:
   fd,tmp=tempfile.mkstemp(prefix=".rg-mod-sched-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w") as f:f.write(patched)
    shutil.copymode(SCHED,tmp);os.replace(tmp,SCHED)
   finally:pathlib.Path(tmp).unlink(missing_ok=True)
  out=call([sys.executable,str(MOD),"once"]).strip()
 except Exception:
  for orig,backup in reversed(backups):shutil.copy2(backup,orig)
  if not any(orig==MOD for orig,backup in backups):MOD.unlink(missing_ok=True)
  raise
 print(json.dumps({"status":"INSTALLED_SHADOW_ONLY","scheduler_hook":True,"projection":json.loads(out),"sending_enabled":False}))
if __name__=="__main__":main()
