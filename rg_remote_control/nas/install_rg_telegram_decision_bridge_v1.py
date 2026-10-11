#!/usr/bin/env python3
"""RG Telegram one-shot NAS decision bridge bootstrap, shadow only.
Fetch pinned PRIVATE repo source using NAS-held GitHub token, never display token.
Does not configure credentials, invoke Cloudflare, or send Telegram updates.
"""
import base64,datetime,json,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
SECRETS=ROOT/"RG_SECRETS"
REPO="RushaGoodbye/rasha-goodbye-news-bot"
COMMIT="c39c82e5d8276e75d9bb1c268f4057201d93a8da"
IMPORT="nas/rg_telegram_cf_decision_import_v1.py"
SCRIPT=STATE/"rg_telegram_cf_decision_import_v1.py"
SCHED=ROOT/"RG_NAS_SCHEDULER_TICK.sh"
MARK="RG_CF_DECISION_SHADOW_IMPORT_V1"
HOOK='''# RG_CF_DECISION_SHADOW_IMPORT_V1
if [ -f "$ROOT/RG_TELEGRAM_STATE/rg_telegram_cf_decision_import_v1.py" ] && [ -s "$ROOT/RG_SECRETS/rg_cf_migration_endpoint" ] && [ -s "$ROOT/RG_SECRETS/rg_cf_migration_run_key" ]; then
  RG_CF_MIGRATION_URL="$(head -n 1 "$ROOT/RG_SECRETS/rg_cf_migration_endpoint")"
  /usr/bin/python3 "$ROOT/RG_TELEGRAM_STATE/rg_telegram_cf_decision_import_v1.py" once --endpoint "$RG_CF_MIGRATION_URL" --key-file "$ROOT/RG_SECRETS/rg_cf_migration_run_key" >> "$ROOT/RG_TELEGRAM_STATE/moderation_import.log" 2>&1 || true
fi
'''
ANCHOR='AUTODEPLOY="$ROOT/RG_NAS_AUTO_DEPLOY.sh"'
def fetch_source():
 tokenpath=SECRETS/"github_token"
 if not tokenpath.is_file():raise RuntimeError("NAS_GITHUB_TOKEN_MISSING")
 token=tokenpath.read_text(encoding="utf-8").strip()
 if len(token)<10 or len(token)>500:raise RuntimeError("NAS_GITHUB_TOKEN_INVALID")
 url="https://api.github.com/repos/"+REPO+"/contents/"+IMPORT+"?ref="+COMMIT
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","User-Agent":"RG-NAS-Shadow-Bridge"})
 with urllib.request.urlopen(req,timeout=20) as response:body=response.read(300001)
 data=json.loads(body)
 if data.get("encoding")!="base64" or not isinstance(data.get("content"),str):raise RuntimeError("SOURCE_ENCODING")
 result=base64.b64decode(data["content"],validate=False)
 if len(result)>100000 or not result.startswith(b"#!/usr/bin/env python3"):raise RuntimeError("SOURCE_VALIDATION")
 return result
def call(args):
 p=subprocess.run(args,text=True,capture_output=True,timeout=35)
 if p.returncode:raise RuntimeError("VALIDATION_FAILED:"+pathlib.Path(args[1]).name)
 return p.stdout
def main():
 if len(sys.argv)>1 and sys.argv[1]=="status":
  print(json.dumps({"status":"BRIDGE_STATUS","importer_installed":SCRIPT.is_file(),"scheduler_hook":SCHED.is_file() and MARK in SCHED.read_text(errors="replace"),"endpoint_configured":(SECRETS/"rg_cf_migration_endpoint").is_file(),"run_key_configured":(SECRETS/"rg_cf_migration_run_key").is_file(),"telegram_sender_enabled":False}))
  return
 if not SCHED.is_file() or SCHED.is_symlink() or not (STATE/"rg_telegram_nas_event_intake_v1.py").is_file():raise RuntimeError("PREREQUISITES_MISSING")
 source=fetch_source()
 with tempfile.TemporaryDirectory(prefix="rgbridge_") as d:
  staging=pathlib.Path(d)/SCRIPT.name
  staging.write_bytes(source)
  call([sys.executable,"-m","py_compile",str(staging)])
  call([sys.executable,str(staging),"selftest"])
  before=SCHED.read_text(encoding="utf-8")
  if MARK in before:patched=before
  elif before.count(ANCHOR)==1:patched=before.replace(ANCHOR,HOOK+"\n"+ANCHOR)
  else:raise RuntimeError("SCHEDULER_LAYOUT")
  p=subprocess.run(["/bin/sh","-n"],text=True,input=patched,capture_output=True)
  if p.returncode:raise RuntimeError("SCHEDULER_SYNTAX")
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
  if SCRIPT.exists():shutil.copy2(SCRIPT,STATE/(SCRIPT.name+"."+stamp+".bak"))
  shutil.copy2(staging,SCRIPT)
  if patched!=before:
   backup=SCHED.with_name(SCHED.name+".bridge-backup-"+stamp)
   shutil.copy2(SCHED,backup)
   fd,tmp=tempfile.mkstemp(prefix=".rg-sched-",dir=str(SCHED.parent))
   try:
    with os.fdopen(fd,"w") as o:o.write(patched)
    shutil.copymode(SCHED,tmp)
    os.replace(tmp,SCHED)
   finally:pathlib.Path(tmp).unlink(missing_ok=True)
 print(json.dumps({"status":"BRIDGE_INSTALLED","importer_selftest":"PASS","scheduler_hook":True,"endpoint_configured":(SECRETS/"rg_cf_migration_endpoint").is_file(),"run_key_configured":(SECRETS/"rg_cf_migration_run_key").is_file(),"telegram_sender_enabled":False}))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","reason":str(exc).split(":")[0][:100],"sending_enabled":False}),file=sys.stderr)
  sys.exit(1)
