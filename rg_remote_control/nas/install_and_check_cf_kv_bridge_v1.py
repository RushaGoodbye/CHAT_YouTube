#!/usr/bin/env python3
"""Safe install of KV-only moderation importer from the private bot repository."""
import base64,json,os,pathlib,shutil,subprocess,sys,tempfile,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
DEST=STATE/"rg_telegram_cf_kv_decision_bridge_v1.py"
TOKEN=ROOT/"RG_SECRETS/github_token"
SHA="0701508fc1dbf74db014bc956d667e044e552b1d"
def main():
 if not TOKEN.is_file() or not (STATE/"migration_shadow.sqlite3").is_file():raise ValueError("missing_prerequisite")
 token=TOKEN.read_text().strip()
 path="nas/rg_telegram_cf_kv_decision_bridge_v1.py"
 url="https://api.github.com/repos/RushaGoodbye/rasha-goodbye-news-bot/contents/"+path+"?ref="+SHA
 request=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","User-Agent":"RG-NAS-KV-Bridge"})
 with urllib.request.urlopen(request,timeout=15) as res:doc=json.loads(res.read(240000))
 source=base64.b64decode(doc["content"])
 if not source.startswith(b"#!/usr/bin/env python3") or len(source)>100000:raise ValueError("source_invalid")
 with tempfile.TemporaryDirectory() as directory:
  p=pathlib.Path(directory)/DEST.name
  p.write_bytes(source)
  for cmd in ([sys.executable,"-m","py_compile",str(p)],[sys.executable,str(p),"selftest"]):
   run=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
   if run.returncode:raise RuntimeError("preinstall_test_failed")
  if DEST.exists():shutil.copy2(DEST,DEST.with_suffix(".py.previous"))
  temp=STATE/("."+DEST.name+".new")
  temp.write_bytes(source)
  os.replace(temp,DEST)
 print(json.dumps({"status":"KV_BRIDGE_INSTALLED","selftest":"PASS","worker_deploy":False,"telegram_sends":0}))
 run=subprocess.run([sys.executable,str(DEST),"once"],capture_output=True,text=True,timeout=50)
 print(run.stdout.strip() or run.stderr.strip())
 if run.returncode:sys.exit(run.returncode)
 run=subprocess.run([sys.executable,str(DEST),"status"],capture_output=True,text=True,timeout=10)
 print(run.stdout.strip())
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","error_class":type(exc).__name__,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
