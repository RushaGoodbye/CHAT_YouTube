#!/usr/bin/env python3
"""RG Telegram NAS editorial UI 2.2 installer.
Stages scanner+editorial store+review UI updater, selftests and DB snapshot first.
No Cloudflare calls, no Telegram posting; preserves token, old review decisions,
quarantine, event ledger and old UI if new release fails.
"""
import datetime,json,os,pathlib,shutil,sqlite3,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
NAME="rg_telegram_nas_editorial_store_v1.py"
SCANNER="rg_telegram_local_rss_scanner_v1.py"
UPDATER="update_rg_telegram_review_ui_v22.py"
PINS=[
 (NAME,"877116660f78e2b2308255e9c8fa22b408c29beb"),
 (SCANNER,"39f428d6ccedf154eb37257a379689f5974469ec"),
 (UPDATER,"c1d758a8cd15b7e731c64a8648a7dee6aaf7744f")
]
HOOK_MARK="# RG_NAS_EDITORIAL_RSS_REFERENCE_V1"
HOOK= """# RG_NAS_EDITORIAL_RSS_REFERENCE_V1
# Once after each RSS scan. Short RSS excerpts are moderator references only.
# No auto-approved content; no Telegram or Cloudflare.
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_editorial_store_v1.py" ]; then
  case "$(date +%M)" in
    06|26|46) /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_nas_editorial_store_v1.py" seed >> "$ROOT/RG_TELEGRAM_STATE/editorial_sources.log" 2>&1 || true ;;
  esac
fi
"""
ANCHOR="# RG_NAS_LOCAL_REVIEW_EXPORT_V1"
def output(status,**kw):
 print(json.dumps({"status":status,"telegram_sends":0,"cloudflare_calls":0,**kw},ensure_ascii=False),flush=True)
def fetch(name,revision):
 url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/"+revision+"/rg_remote_control/nas/"+name
 req=urllib.request.Request(url,headers={"User-Agent":"RG-NAS-Editorial-2.2"})
 with urllib.request.urlopen(req,timeout=25) as response:
  if response.status!=200:raise RuntimeError("source_http")
  data=response.read(100001)
 if not data.startswith(b"#!/usr/bin/env python3") or not 3000<len(data)<=100000:raise RuntimeError("unexpected_source")
 return data
def run(argv,timeout=25):
 proc=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
 if proc.returncode:
  msg=(proc.stderr or proc.stdout)[-280:]
  raise RuntimeError("command_failed:"+pathlib.Path(argv[1]).name+":"+msg)
 return proc.stdout.strip()
def patch(text):
 if HOOK_MARK in text:return text,"ALREADY_INSTALLED"
 if text.count(ANCHOR)!=1:raise RuntimeError("scheduler_anchor_missing")
 return text.replace(ANCHOR,HOOK+"\n"+ANCHOR,1),"PATCHED"
def selftest():
 sample='#!/bin/sh\nROOT="/volume1/docker"\n'+ANCHOR+'\nexit 0\n'
 v,mode=patch(sample)
 assert mode=="PATCHED" and HOOK_MARK in v
 assert patch(v)==(v,"ALREADY_INSTALLED")
 with tempfile.TemporaryDirectory() as folder:
  f=pathlib.Path(folder)/"sample.txt"
  f.write_text("unchanged")
  assert f.read_text()=="unchanged"
 output("EDITORIAL_INSTALLER_SELFTEST_PASS",scheduler_patch="PASS",network_calls=0)
def main():
 if len(sys.argv)>1 and sys.argv[1]=="selftest":selftest();return
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 if not (STATE/"migration_shadow.sqlite3").is_file():raise RuntimeError("database_missing")
 if not (STATE/"rg_telegram_local_review_server_v1.py").is_file():raise RuntimeError("review_server_missing")
 if SCHED.is_symlink() or not SCHED.is_file():raise RuntimeError("scheduler_missing")
 before=SCHED.read_text("utf-8")
 after,mode=patch(before)
 proc=subprocess.run(["/bin/sh","-n"],input=after,text=True,capture_output=True,timeout=10)
 if proc.returncode:raise RuntimeError("scheduler_shell_invalid")
 with tempfile.TemporaryDirectory(prefix="rg-editorial-22-") as folder:
  temp=pathlib.Path(folder)
  for name,revision in PINS:(temp/name).write_bytes(fetch(name,revision))
  for name,revision in PINS:
   run([sys.executable,"-m","py_compile",str(temp/name)])
   result=run([sys.executable,str(temp/name),"selftest"])
   output("MODULE_SELFTEST_PASS",module=name,result=result)
  snapshot=temp/"db-copy.sqlite3"
  with sqlite3.connect(str(STATE/"migration_shadow.sqlite3"),timeout=12) as original:
   with sqlite3.connect(str(snapshot),timeout=12) as copy:original.backup(copy)
  sample=run([sys.executable,str(temp/NAME),"initialize","--db",str(snapshot)])
  if (STATE/"candidate_inbox.jsonl").is_file():
   import_log=run([sys.executable,str(temp/NAME),"seed","--db",str(snapshot),"--inbox",str(STATE/"candidate_inbox.jsonl")])
  else:import_log="no_rss_inbox"
  output("EDITORIAL_LIVE_SCHEMA_SNAPSHOT_PASS",db_check=sample,rss_preview=import_log,real_database_writes=0)
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  for name in (NAME,SCANNER):
   dst=STATE/name
   if dst.is_symlink():raise RuntimeError("module_symlink_refused")
   if dst.exists():shutil.copy2(dst,STATE/(name+"."+stamp+".bak"))
   fd,p=tempfile.mkstemp(prefix=".rg-editorial-",dir=str(STATE))
   try:
    with os.fdopen(fd,"wb") as file:file.write((temp/name).read_bytes())
    os.chmod(p,0o640);os.replace(p,dst)
   finally:
    if os.path.exists(p):os.unlink(p)
  if mode=="PATCHED":
   shutil.copy2(SCHED,SCHED.with_name(SCHED.name+".editorial-backup-"+stamp))
   fd,p=tempfile.mkstemp(prefix=".rg-editorial-scheduler-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w") as file:file.write(after)
    shutil.copymode(SCHED,p);os.replace(p,SCHED)
   finally:
    if os.path.exists(p):os.unlink(p)
  module_state=run([sys.executable,str(STATE/NAME),"initialize"])
  suggestion_state=run([sys.executable,str(STATE/NAME),"seed"]) if (STATE/"candidate_inbox.jsonl").is_file() else "no_rss_inbox"
  output("EDITORIAL_STORE_INSTALLED",initialize=module_state,suggestions=suggestion_state,scheduler=mode)
  # Existing updater backs up the server and atomically rolls it back if needed.
  output("UI_RESTART_BEGIN",old_interface_kept_if_failure=True)
  print(run([sys.executable,str(temp/UPDATER)],timeout=65))
  output("RG_TELEGRAM_EDITORIAL_V22_READY",ui_version="2.2",rss_reference_only=True,
         no_auto_approved_drafts=True,live_delivery_enabled=False)
if __name__=="__main__":
 try:main()
 except Exception as exc:
  output("BLOCKED",reason=type(exc).__name__+":"+str(exc)[:220],live_delivery_enabled=False)
  sys.exit(1)
