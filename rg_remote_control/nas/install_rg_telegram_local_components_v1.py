#!/usr/bin/env python3
"""Install and self-test local NAS candidate ingestion + moderation v2.
NO Cloudflare calls, NO Telegram, NO deploy. Additive scheduler hook only.
"""
import datetime,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request,json
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
REPO="RushaGoodbye/CHAT_YouTube"
REV_INGEST="43200d08c8265fc39f0620916b9330f49c1f9e2f"
REV_PROJECTION="a08664f89bd0c9d9c3e2fe5e397a591d4be8e1d3"
FILENAMES=[
 ("rg_telegram_local_candidate_ingest_v1.py",REV_INGEST),
 ("rg_telegram_moderation_projection_v1.py",REV_PROJECTION),
 ("rg_telegram_local_rss_scanner_v1.py","3859c9a1f7322a114a1762314c57f6b483186758"),
]
MARK="RG_NAS_LOCAL_CANDIDATE_INGEST_V1"
ANCHOR="# RG_NAS_SHADOW_RUNTIME_V1_BEGIN"
HOOK='''# RG_NAS_LOCAL_CANDIDATE_INGEST_V1
# Public RSS shadow scan at most 3 times/hour. Only articles with photo.
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_local_rss_scanner_v1.py" ]; then
  case "$(date +%M)" in
    05|25|45) /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_local_rss_scanner_v1.py" once >> "$ROOT/RG_TELEGRAM_STATE/local_rss_scanner.log" 2>&1 || true ;;
  esac
fi
# File-only intake; the existing moderation projection consumes saved events.
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_local_candidate_ingest_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_local_candidate_ingest_v1.py" once >> "$ROOT/RG_TELEGRAM_STATE/local_candidate_ingest.log" 2>&1 || true
fi
'''
def fetch(filename,commit):
 path="rg_remote_control/nas/"+filename
 url="https://raw.githubusercontent.com/"+REPO+"/"+commit+"/"+path
 req=urllib.request.Request(url,headers={"User-Agent":"RG-NAS-Local-Install/1.0"})
 with urllib.request.urlopen(req,timeout=20) as resp:
  if resp.status!=200:raise RuntimeError("fetch_not_200")
  body=resp.read(120001)
 if not body.startswith(b"#!/usr/bin/env python3") or len(body)>120000:raise RuntimeError("unexpected_source")
 return body
def execute(cmd,timeout=25):
 result=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
 if result.returncode:raise RuntimeError("selftest_failed:"+pathlib.Path(cmd[1]).name)
 return result.stdout.strip()
def main():
 if len(sys.argv)>1 and sys.argv[1]=="status":
  print(json.dumps({"status":"LOCAL_COMPONENTS","intake_installed":(STATE/FILENAMES[0][0]).is_file(),"moderation_installed":(STATE/FILENAMES[1][0]).is_file(),"scheduler_hook":SCHED.is_file() and MARK in SCHED.read_text(errors="replace"),"telegram_sends":0}))
  return
 if not STATE.is_dir() or not (STATE/"migration_shadow.sqlite3").is_file():raise RuntimeError("missing_shadow_db")
 if not (STATE/"rg_telegram_nas_event_intake_v1.py").is_file():raise RuntimeError("event_intake_missing")
 if SCHED.is_symlink() or not SCHED.is_file():raise RuntimeError("scheduler_missing")
 with tempfile.TemporaryDirectory(prefix="rg-local-") as directory:
  stage=pathlib.Path(directory)
  for name,commit in FILENAMES:(stage/name).write_bytes(fetch(name,commit))
  shutil.copy2(STATE/"rg_telegram_nas_event_intake_v1.py",stage/"rg_telegram_nas_event_intake_v1.py")
  tests=[]
  for name,commit in FILENAMES:
   p=stage/name
   execute([sys.executable,"-m","py_compile",str(p)])
   tests.append({"module":name,"selftest":execute([sys.executable,str(p),"selftest"])})
  before=SCHED.read_text("utf-8")
  if MARK in before:patched=before
  elif before.count(ANCHOR)==1:patched=before.replace(ANCHOR,HOOK+"\n"+ANCHOR)
  else:raise RuntimeError("scheduler_anchor_invalid")
  syntax=subprocess.run(["/bin/sh","-n"],input=patched,text=True,capture_output=True,timeout=10)
  if syntax.returncode:raise RuntimeError("scheduler_syntax_failed")
  stamp=datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
  for name,commit in FILENAMES:
   dest=STATE/name
   if dest.exists():shutil.copy2(dest,STATE/(name+"."+stamp+".bak"))
   fd,tmp=tempfile.mkstemp(prefix=".rg-local-",dir=str(STATE))
   try:
    with os.fdopen(fd,"wb") as o:o.write((stage/name).read_bytes())
    os.chmod(tmp,0o640)
    os.replace(tmp,dest)
   finally:
    if os.path.exists(tmp):os.unlink(tmp)
  if patched!=before:
   shutil.copy2(SCHED,SCHED.with_name(SCHED.name+".local-backup-"+stamp))
   fd,tmp=tempfile.mkstemp(prefix=".rg-local-sched-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w") as o:o.write(patched)
    shutil.copymode(SCHED,tmp)
    os.replace(tmp,SCHED)
   finally:
    if os.path.exists(tmp):os.unlink(tmp)
  print(json.dumps({"status":"LOCAL_COMPONENTS_INSTALLED","selftests":"PASS","tests":tests,"scheduler_hook":MARK in SCHED.read_text(errors="replace"),"cloudflare_calls":0,"telegram_sends":0,"local_news_inbox":str(STATE/"candidate_inbox.jsonl"),"rss_sources":2},ensure_ascii=False))
  for name,mode in [(FILENAMES[2][0],"once"),(FILENAMES[0][0],"once"),(FILENAMES[1][0],"once"),(FILENAMES[0][0],"status")]:
   print(execute([sys.executable,str(STATE/name),mode]))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","reason":str(exc)[:140],"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
