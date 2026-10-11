#!/usr/bin/env python3
"""Upgrade the NAS local-news chain: dated RSS, versioned intake, review board.
No Cloudflare or Telegram calls; does not change approval or publication state.
"""
import datetime,json,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
SOURCE="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/"
SCRIPTS=(
 ("rg_telegram_local_candidate_ingest_v1.py","9df4b66a2527c2d55fd02389519448639a449316"),
 ("rg_telegram_local_rss_scanner_v1.py","b3769e3163740f6145f9ca4d3560193d57844222"),
 ("rg_telegram_local_review_export_v1.py","ad0f62cfd0f2ff82b19b139b988afcd2192c4f6c"),
)
HOOK_MARK="# RG_NAS_LOCAL_REVIEW_EXPORT_V1"
ANCHORS=("# RG_NAS_SHADOW_RUNTIME_V1_END",'AUTODEPLOY="$ROOT/RG_NAS_AUTO_DEPLOY.sh"',"# RG_NAS_SHADOW_RUNTIME_V1_BEGIN")
HOOK='''# RG_NAS_LOCAL_REVIEW_EXPORT_V1
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_local_review_export_v1.py" ]; then
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_local_review_export_v1.py" once >> "$ROOT/RG_TELEGRAM_STATE/local_review_export.log" 2>&1 || true
fi
'''
def choose_hook(before):
 if HOOK_MARK in before:return before,"ALREADY_INSTALLED"
 anchor=next((a for a in ANCHORS if before.count(a)==1),None)
 if not anchor:return before,"UNSUPPORTED_SCHEDULER_LAYOUT"
 return before.replace(anchor,HOOK+"\n"+anchor,1),"PATCHED"
def selftest():
 for anchor in ANCHORS:
  base='#!/bin/sh\nROOT="/volume1/docker"\n'+anchor+'\nexit 0\n'
  once,status=choose_hook(base)
  assert status=="PATCHED" and once.count(HOOK_MARK)==1
  twice,status=choose_hook(once)
  assert status=="ALREADY_INSTALLED" and once==twice
 text,status=choose_hook('#!/bin/sh\nexit 0\n')
 assert status=="UNSUPPORTED_SCHEDULER_LAYOUT" and text=='#!/bin/sh\nexit 0\n'
 print(json.dumps({"selftest":"PASS","scheduler_idempotent":"PASS","no_sends":True}))
def download(name,commit):
 url=SOURCE+commit+"/rg_remote_control/nas/"+name
 req=urllib.request.Request(url,headers={"User-Agent":"RG-Local-News-Upgrade"})
 with urllib.request.urlopen(req,timeout=20) as r:data=r.read(140001)
 if len(data)>140000 or not data.startswith(b"#!/usr/bin/env python3"):raise ValueError("untrusted_script")
 return data
def command(cmd,timeout=20):
 r=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout)
 if r.returncode:raise RuntimeError("validation_failed:"+pathlib.Path(cmd[1]).name)
 return r.stdout.strip()
def main():
 if len(sys.argv)>1 and sys.argv[1]=="selftest":selftest();return
 selftest()
 if not (STATE/"migration_shadow.sqlite3").is_file() or not (STATE/"rg_telegram_nas_event_intake_v1.py").is_file():raise ValueError("local_prerequisites_missing")
 if not SCHED.is_file() or SCHED.is_symlink():raise ValueError("nas_scheduler_missing")
 with tempfile.TemporaryDirectory(prefix="rg-local-v2-") as tmp:
  stage=pathlib.Path(tmp)
  for name,commit in SCRIPTS:(stage/name).write_bytes(download(name,commit))
  shutil.copy2(STATE/"rg_telegram_nas_event_intake_v1.py",stage/"rg_telegram_nas_event_intake_v1.py")
  checks=[]
  for name,commit in SCRIPTS:
   p=stage/name
   command([sys.executable,"-m","py_compile",str(p)])
   checks.append({"name":name,"result":command([sys.executable,str(p),"selftest"])})
  before=SCHED.read_text("utf-8")
  after,sched_status=choose_hook(before)
  if subprocess.run(["/bin/sh","-n"],input=after,text=True,capture_output=True,timeout=10).returncode:raise RuntimeError("shell_syntax_error")
  date=datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
  for name,commit in SCRIPTS:
   dest=STATE/name
   if dest.exists():shutil.copy2(dest,dest.with_name(name+"."+date+".bak"))
   fd,tmpdest=tempfile.mkstemp(prefix=".rg-news-",dir=str(STATE))
   try:
    with os.fdopen(fd,"wb") as output:output.write((stage/name).read_bytes())
    os.chmod(tmpdest,0o640);os.replace(tmpdest,dest)
   finally:
    if os.path.exists(tmpdest):os.unlink(tmpdest)
  if after!=before:
   shutil.copy2(SCHED,SCHED.with_name(SCHED.name+".local-v2-backup-"+date))
   fd,tmpdest=tempfile.mkstemp(prefix=".rg-news-sched-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w") as output:output.write(after)
    shutil.copymode(SCHED,tmpdest);os.replace(tmpdest,SCHED)
   finally:
    if os.path.exists(tmpdest):os.unlink(tmpdest)
  # Ingest one refresh and regenerate the browser-readable review board.
  scan=subprocess.run([sys.executable,str(STATE/SCRIPTS[1][0]),"once"],text=True,capture_output=True,timeout=50)
  print(scan.stdout.strip() or scan.stderr.strip())
  print(command([sys.executable,str(STATE/SCRIPTS[0][0]),"once"],timeout=30))
  mod=STATE/"rg_telegram_moderation_projection_v1.py"
  if not mod.is_file():raise ValueError("moderation_projection_missing")
  print(command([sys.executable,str(mod),"once"],timeout=30))
  print(command([sys.executable,str(STATE/SCRIPTS[2][0]),"once"],timeout=30))
  print(json.dumps({"status":"LOCAL_NEWS_V2_INSTALLED","selftests":"PASS","checks":checks,"scheduler_mode":sched_status,"delivery_enabled":False,"telegram_sends":0,"cloudflare_calls":0},ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","reason":type(e).__name__+":"+str(e)[:95],"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
