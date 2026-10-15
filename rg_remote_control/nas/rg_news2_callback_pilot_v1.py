#!/usr/bin/env python3
"""RG News2 limited callback automation pilot: at most 3 ticks, 5-min schedule.
NO permanent owner marker; no channel publication; archive-before-ack handled
by the existing rg_news2_controlled_callback_once_v1.py.
Operator-approved controlled trial only. Stop on any nonzero exit.
"""
import datetime,fcntl,json,os,pathlib,shutil,stat,subprocess,sys,tempfile
B=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
O=B/"operator"; CRON=pathlib.Path("/etc/crontab")
T=O/"rg_news2_controlled_callback_once_v1.py"
SELF=O/"callback_pilot_v1.py"
STATE=O/"callback_pilot_state.json"
MARK="# RG_NEWS2_CALLBACK_PILOT_V1"
LINE="*/5\t*\t*\t*\t*\troot\t/usr/bin/python3 /volume1/docker/RG_TELEGRAM_NEWS_2/operator/callback_pilot_v1.py tick >> /volume1/docker/RG_TELEGRAM_NEWS_2/operator/callback_pilot.log 2>&1 "+MARK
def emit(**d):print(json.dumps(d,ensure_ascii=False,sort_keys=True),flush=True)
def save(path,s):
 fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix=".rg_pilot_")
 try:
  with os.fdopen(fd,"w") as f:f.write(s);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,0o600);os.replace(tmp,str(path))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def prerequisites():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if not O.is_dir() or O.is_symlink():raise RuntimeError("OPERATOR_DIR_UNSAFE")
 if not CRON.is_file() or CRON.is_symlink():raise RuntimeError("DSM_CRON_UNAVAILABLE")
 if not (B/"MODERATION_DELIVERY_ENABLED").is_file():raise RuntimeError("DELIVERY_CLOSED")
 if (B/"PUBLISH_ENABLED").exists():raise RuntimeError("PUBLISH_MUST_BE_CLOSED")
 if pathlib.Path("/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled").exists():raise RuntimeError("LEGACY_BOT_ENABLED")
 if (B/"NAS_EXCLUSIVE_OWNER_VERIFIED").exists():raise RuntimeError("OTHER_OWNER_MODE")
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ("install","tick","status","disable"):raise RuntimeError("USAGE")
 mode=sys.argv[1]
 prerequisites()
 cron=CRON.read_text("utf-8")
 ls=cron.splitlines()
 old=[x for x in ls if MARK in x]
 if any(x!=LINE for x in old):raise RuntimeError("CRON_DRIFT")
 if mode=="status":
  data=json.loads(STATE.read_text()) if STATE.is_file() else {}
  emit(status="PILOT_STATUS",scheduled=LINE in old,trial=data);return
 if mode=="tick":
  if not STATE.is_file():raise RuntimeError("PILOT_NOT_INITIALIZED")
  fd=os.open(str(O/"callback_pilot.lock"),os.O_RDWR|os.O_CREAT,0o600)
  try:
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError:
   emit(status="SKIP_ALREADY_RUNNING");return
  try:
   d=json.loads(STATE.read_text())
   if d.get("halt") or d.get("attempts",0)>=3:
    emit(status="PILOT_FINISHED",attempts=d.get("attempts"));return
   d["attempts"]+=1
   save(STATE,json.dumps(d))
   p=subprocess.run(["/usr/bin/python3",str(T),"once"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=60)
   if p.returncode!=0:
    d["halt"]=True;d["last_result"]="BLOCKED";save(STATE,json.dumps(d))
    emit(status="PILOT_HALTED_ON_ERROR",attempts=d["attempts"],details=p.stdout[-800:]);return
   # Do not store raw updates here; the one-shot handler does so privately.
   d["last_result"]="PASS";save(STATE,json.dumps(d))
   emit(status="PILOT_TICK_DONE",attempts=d["attempts"],max_attempts=3,details=p.stdout[-1000:])
  finally:os.close(fd)
  return
 if mode=="install":
  src=pathlib.Path("/tmp/rg_news2_callbacks.py")
  if not src.is_file() or src.is_symlink():raise RuntimeError("VERIFIED_ONE_SHOT_MISSING")
  s=src.read_text("utf-8")
  if "updates_handoff_" not in s or "process_callback" not in s or "getUpdates" not in s:raise RuntimeError("UNKNOWN_CALLBACK_SCRIPT")
  if STATE.exists():raise RuntimeError("EXISTING_PILOT_REQUIRES_REVIEW")
  if not SELF.is_file():raise RuntimeError("INSTALL_FILE_NOT_STAGED")
  shutil.copyfile(str(src),str(T));os.chmod(str(T),0o600)
  save(STATE,json.dumps({"attempts":0,"halt":False,"last_result":"NOT_RUN"}))
 target="\n".join([x for x in ls if MARK not in x]+([LINE] if mode=="install" else []))+"\n"
 if target!=cron:
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  back=O/("etc_crontab_before_callback_pilot_"+stamp)
  if back.exists():raise RuntimeError("BACKUP_COLLISION")
  back.write_text(cron);os.chmod(str(back),0o600)
  modebits=stat.S_IMODE(CRON.stat().st_mode)
  fd,tmp=tempfile.mkstemp(dir="/etc",prefix=".rg_callback_cron_")
  try:
   with os.fdopen(fd,"w") as f:f.write(target);f.flush();os.fsync(f.fileno())
   os.chmod(tmp,modebits);os.chown(tmp,0,0);os.replace(tmp,str(CRON))
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 emit(status="PILOT_INSTALLED" if mode=="install" else "PILOT_DISABLED",scheduled=(mode=="install"),max_attempts=3,cron_reload_confirmed=False,telegram_calls=0,channel_sends=0)
if __name__=="__main__":
 try:main()
 except Exception as e:
  emit(status="BLOCKED",reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__)
  sys.exit(1)
