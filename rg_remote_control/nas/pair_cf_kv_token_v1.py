#!/usr/bin/env python3
"""Interactive one-time least-privilege KV token pairing on Synology. Requires terminal.
No token is passed in arguments, stdout or shell history.
"""
import getpass,json,os,pathlib,stat,sys,tempfile,urllib.request,urllib.error
ROOT=pathlib.Path("/volume1/docker/RG_SECRETS")
DEST=ROOT/"rg_cf_kv_read_token"
ACCOUNT="be73f73dbe2a5471c62384dc673c91e6"
NS="d7852688b21b4185b8748b1aa940d978"
def check(token,route):
 req=urllib.request.Request("https://api.cloudflare.com/client/v4/"+route,headers={"Authorization":"Bearer "+token,"Accept":"application/json","User-Agent":"RG-NAS-KV-Pairing/1.0"})
 try:
  with urllib.request.urlopen(req,timeout=15) as r:return r.status
 except urllib.error.HTTPError as e:return e.code
def main():
 if not os.isatty(0):raise RuntimeError("terminal_required")
 if DEST.is_symlink():raise RuntimeError("secret_path_symlink")
 print("Paste the new RG TELEGRAM NAS KV READ token (input is hidden).")
 token=getpass.getpass("Cloudflare KV token: ").strip()
 if not 20<=len(token)<=512 or any(x.isspace() for x in token):raise RuntimeError("invalid_token_format")
 auth=check(token,"user/tokens/verify")
 kv=check(token,"accounts/"+ACCOUNT+"/storage/kv/namespaces/"+NS+"/keys?limit=1")
 if auth!=200 or kv!=200:
  print(json.dumps({"status":"BLOCKED","token_verify_http":auth,"kv_read_http":kv,"saved":False}))
  return 1
 ROOT.mkdir(parents=True,exist_ok=True)
 os.chmod(ROOT,0o700) if ROOT.stat().st_mode & stat.S_IWOTH else None
 fd,tmp=tempfile.mkstemp(prefix=".rg-cf-kv-",dir=str(ROOT))
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,"w") as f:f.write(token+"\n")
  os.replace(tmp,DEST)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 os.chmod(DEST,0o600)
 print(json.dumps({"status":"KV_TOKEN_PAIRED","token_verify_http":auth,"kv_read_http":kv,"permissions":"0600","deploy_token_untouched":True}))
 return 0
if __name__=="__main__":
 try:sys.exit(main())
 except Exception as e:
  print(json.dumps({"status":"BLOCKED","reason":type(e).__name__}))
  sys.exit(1)
