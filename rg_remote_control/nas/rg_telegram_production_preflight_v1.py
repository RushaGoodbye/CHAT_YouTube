#!/usr/bin/env python3
"""RG Telegram production deploy preflight v1. Read-only, zero Cloudflare calls."""
import base64,json,os,pathlib,subprocess,sys,tempfile,urllib.error,urllib.request,shutil
ROOT=pathlib.Path("/volume1/docker")
TOKEN_FILE=ROOT/"RG_SECRETS/github_token"
REPO="RushaGoodbye/rasha-goodbye-news-bot"
REF="4bea0d70d2f29b1a1bef10d23bdae51f9799f595"
FILES=["nas/RG_NAS_ADMIN_CONTROL_INSTALL.sh","cloudflare-admin-control/package.json","cloudflare-admin-control/wrangler.toml","cloudflare-admin-control/src/index.js","cloudflare-admin-control/src/health-freshness.js","cloudflare-admin-control/scripts/test-health-freshness.mjs"]
def fetch(path,token):
 url="https://api.github.com/repos/"+REPO+"/contents/"+path+"?ref="+REF
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","User-Agent":"RG-Telegram-Preflight"})
 with urllib.request.urlopen(req,timeout=20) as resp:d=json.loads(resp.read(3000000))
 if d.get("encoding")!="base64" or d.get("type")!="file":raise ValueError("github_format")
 data=base64.b64decode(d["content"])
 if not 0<len(data)<2000000:raise ValueError("empty_or_oversize")
 return data
def main():
 if not TOKEN_FILE.is_file():raise ValueError("github_token_missing")
 token=TOKEN_FILE.read_text().strip()
 report=[]
 with tempfile.TemporaryDirectory(prefix="rg-telegram-preflight-") as temp:
  path=pathlib.Path(temp)
  for rel in FILES:
   try:
    data=fetch(rel,token)
    dest=path/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    report.append({"file":rel,"status":"PASS","bytes":len(data)})
   except (urllib.error.HTTPError,urllib.error.URLError,ValueError,KeyError,TimeoutError) as exc:
    report.append({"file":rel,"status":"ERROR","error":type(exc).__name__})
  if all(x["status"]=="PASS" for x in report):
   install=path/FILES[0]
   p=subprocess.run(["sh","-n",str(install)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
   report.append({"check":"shell_syntax","status":"PASS" if p.returncode==0 else "ERROR"})
   package=json.loads((path/FILES[1]).read_text())
   targets=["scripts/test-health-freshness.mjs","src/index.js","src/health-freshness.js"]
   report.append({"check":"package_sources","status":"PASS" if all((path/"cloudflare-admin-control"/q).is_file() for q in targets) and "test-health-freshness.mjs" in package.get("scripts",{}).get("check","") else "ERROR"})
   src=install.read_text()
   report.append({"check":"installer_decodes_github_api","status":"PASS" if "base64.b64decode" in src and "github+json" in src else "ERROR"})
   if subprocess.run(["sh","-c","command -v node >/dev/null 2>&1"],stdout=subprocess.DEVNULL).returncode==0:
    for rel in ("cloudflare-admin-control/src/index.js","cloudflare-admin-control/src/health-freshness.js","cloudflare-admin-control/scripts/test-health-freshness.mjs"):
     p=subprocess.run(["node","--check",str(path/rel)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
     report.append({"check":"js_syntax:"+rel,"status":"PASS" if p.returncode==0 else "ERROR"})
   # Run the actual regression suite in an isolated local Node container.
   # This does not access Cloudflare or publish. Node dependencies are built-in.
   docker_bin=shutil.which("docker") or next((p for p in ("/usr/local/bin/docker","/var/packages/ContainerManager/target/usr/bin/docker","/var/packages/Docker/target/usr/bin/docker") if os.path.isfile(p) and os.access(p,os.X_OK)),None)
   if docker_bin:
    docker=subprocess.run([docker_bin,"image","inspect","node:22-bookworm-slim"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    if docker.returncode==0:
     cp=subprocess.run([docker_bin,"run","--rm","--network","none","--read-only","-v",str(path/"cloudflare-admin-control")+":/app:ro","-w","/app","node:22-bookworm-slim","node","scripts/test-health-freshness.mjs"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
     report.append({"check":"health_freshness_regression","status":"PASS" if cp.returncode==0 else "ERROR","exit_code":cp.returncode})
    else:report.append({"check":"health_freshness_regression","status":"WARNING","reason":"node_image_not_cached"})
   else:report.append({"check":"health_freshness_regression","status":"WARNING","reason":"docker_unavailable"})
 summary={x:sum(v.get("status")==x for v in report) for x in ("PASS","WARNING","ERROR")}
 print(json.dumps({"schema":"RG_TELEGRAM_PRODUCTION_PREFLIGHT_V1","overall":"ERROR" if summary["ERROR"] else "WARNING" if summary["WARNING"] else "PASS","commit":REF[:12],"summary":summary,"checks":report,"cloudflare_calls":0,"telegram_sends":0,"production_changes":0},ensure_ascii=False,indent=2))
 return 0 if not summary["ERROR"] else 2
if __name__=="__main__":
 try:sys.exit(main())
 except Exception as e:
  print(json.dumps({"overall":"ERROR","error":type(e).__name__,"cloudflare_calls":0,"telegram_sends":0}))
  sys.exit(2)
