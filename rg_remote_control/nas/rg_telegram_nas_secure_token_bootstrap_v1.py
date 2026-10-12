#!/usr/bin/env python3
"""RG Telegram NAS: securely identify/import EXISTING bot token.
Requires a separately downloaded pinned rg_telegram_nas_transport_preflight_v1.py
to perform only getMe/getChat/getChatMember reads.
Never prints a token, sends messages, calls Cloudflare or rotates BotFather token.
"""
import argparse,getpass,importlib.util,json,os,pathlib,re,stat,subprocess,sys,tempfile
ROOT=pathlib.Path("/volume1/docker")
SECRETS=ROOT/"RG_SECRETS"
TARGET=SECRETS/"rg_telegram_bot_token"
PRE=pathlib.Path("/tmp/rg_bot_preflight.py")
TOKEN_PATTERN=re.compile(r"^[0-9]{5,13}:[A-Za-z0-9_-]{25,}$")
APP_DIRS=("RG_ALERTS_DEPLOY","RG_CONTENT_DEPLOY","RG_DEPLOY","RG_TELEGRAM_STATE","RG_NAS_CONTROL")
KNOWN_FILES=("rg_telegram_bot_token","telegram_bot_token","telegram_token","bot_token")
ENV_KEYS=("TELEGRAM_BOT_TOKEN","TELEGRAM_TOKEN","RG_TELEGRAM_BOT_TOKEN")
def status(value,**kwargs):
 print(json.dumps({"status":value,**kwargs,"telegram_sends":0,"cloudflare_calls":0},ensure_ascii=False),flush=True)
def reader():
 if not PRE.is_file() or PRE.is_symlink():raise RuntimeError("preflight_module_missing")
 spec=importlib.util.spec_from_file_location("rg_readonly_preflight",str(PRE))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module
def maybe_file(path):
 if path.is_symlink() or not path.is_file():return False
 st=path.stat()
 return st.st_size>0 and st.st_size<=131072 and stat.S_ISREG(st.st_mode)
def docker_candidates():
 """Optional read-only search of RG-owned container environment metadata."""
 binary="/usr/local/bin/docker"
 if not pathlib.Path(binary).is_file():return []
 try:
  ps=subprocess.run([binary,"ps","--format","{{.Names}}"],capture_output=True,text=True,timeout=8)
  if ps.returncode:return []
  containers=[n.strip() for n in ps.stdout.splitlines() if n.strip().startswith(("rg-","rg_"))][:25]
  results=[]
  for name in containers:
   task=subprocess.run([binary,"inspect","--format","{{json .Config.Env}}",name],capture_output=True,text=True,timeout=5)
   if task.returncode or len(task.stdout)>262144:continue
   try:records=json.loads(task.stdout)
   except (ValueError,TypeError):continue
   if not isinstance(records,list):continue
   for item in records:
    if not isinstance(item,str) or "=" not in item:continue
    key,value=item.split("=",1)
    if key in ENV_KEYS and TOKEN_PATTERN.fullmatch(value):
     results.append((value,"docker:"+name+":"+key))
  return results
 except (OSError,subprocess.TimeoutExpired):return []
def candidates():
 paths=[]
 for name in KNOWN_FILES:paths.append(SECRETS/name)
 for rootname in APP_DIRS:
  root=ROOT/rootname
  for fname in ("deploy.env",".env",".dev.vars","telegram.env","bot.env","secrets.env"):
   paths.append(root/fname)
  for child in ("cloudflare-alerts","cloudflare-content-hub","cloudflare-video-moderation","app","config"):
   for fname in (".env",".dev.vars","deploy.env","secrets.env","bot.env"):
    paths.append(root/child/fname)
 found=[];seen=set()
 for path in paths:
  if path in seen or not maybe_file(path):continue
  seen.add(path)
  try:
   value=path.read_text("utf-8").strip()
   if TOKEN_PATTERN.fullmatch(value):found.append((value,str(path.relative_to(ROOT))));continue
   data={}
   for line in value.splitlines():
    m=re.match(r"^\s*(?:export\s+)?([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*)$",line)
    if not m:continue
    entry=m.group(2).strip()
    if len(entry)>=2 and entry[0] in "'\"" and entry[-1]==entry[0]:entry=entry[1:-1]
    data[m.group(1)]=entry
   for key in ENV_KEYS:
    entry=data.get(key,"")
    if TOKEN_PATTERN.fullmatch(entry):found.append((entry,str(path.relative_to(ROOT))+":"+key));break
  except (UnicodeError,OSError,ValueError):continue
 found.extend(docker_candidates())
 unique=[];tokens=set()
 for token,where in found:
  if token not in tokens:unique.append((token,where));tokens.add(token)
 return unique
def verify(token,source,preflight):
 result=preflight.probe(token,source)
 if result.get("status")!="TELEGRAM_TRANSPORT_READ_READY":
  raise RuntimeError("bot_not_channel_posting_admin")
 return result
def write_secret(token,dest=TARGET):
 if not TOKEN_PATTERN.fullmatch(token):raise ValueError("bad_token_shape")
 if dest.is_symlink():raise RuntimeError("target_symlink_refused")
 dest.parent.mkdir(parents=True,exist_ok=True)
 if dest.parent.is_symlink():raise RuntimeError("secret_directory_symlink_refused")
 fd,tmp=tempfile.mkstemp(prefix=".rg-tg-token-",dir=str(dest.parent))
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,"w",encoding="utf-8") as out:
   out.write(token+"\n");out.flush();os.fsync(out.fileno())
  os.replace(tmp,dest)
  os.chmod(dest,0o600)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def selftest():
 with tempfile.TemporaryDirectory() as folder:
  dest=pathlib.Path(folder)/"rg_telegram_bot_token"
  fake="12345678:"+("A"*38)
  write_secret(fake,dest)
  assert dest.read_text().strip()==fake
  assert stat.S_IMODE(dest.stat().st_mode)==0o600
  write_secret(fake,dest)
  assert dest.read_text().strip()==fake
  assert not TOKEN_PATTERN.fullmatch("NOT_A_TOKEN")
  # No Docker access or Telegram network is permitted during selftest.
  try:write_secret("NOT_A_TOKEN",dest)
  except ValueError:pass
  else:raise AssertionError("bad token accepted")
 status("TOKEN_BOOTSTRAP_SELFTEST_PASS",secret_file_permission="0600",no_network=True,token_never_logged=True)
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("mode",choices=("selftest","discover","install","install-interactive"))
 args=parser.parse_args()
 if args.mode=="selftest":selftest();return
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 pre=reader()
 options=candidates()
 if args.mode=="discover":
  status("LOCAL_CREDENTIAL_CANDIDATES" if options else "NO_LOCAL_CREDENTIAL_FOUND",
         matching_sources=[p for _,p in options],candidate_count=len(options),
         token_not_printed=True,will_not_touch_secret=True)
  return
 last_error="no_local_candidate"
 for token,where in options:
  try:
   result=verify(token,where,pre)
   write_secret(token)
   status("EXISTING_BOT_TOKEN_READY",source=where,channel=result["channel_username"],
          bot_username=result["bot_username"],bot_can_post=True,
          secret_file="RG_SECRETS/rg_telegram_bot_token",permissions="0600",
          no_message_sent=True,legacy_cloudflare_unchanged=True)
   return
  except (RuntimeError,ValueError) as ex:
   last_error="local_token_probe_failed"
 if args.mode!="install-interactive":
  status("EXISTING_BOT_TOKEN_REQUIRED",reason=last_error,
         token_must_not_be_pasted_in_chat=True,
         next_step="Run install-interactive with existing token on NAS terminal",
         production_post_enabled=False)
  return
 if not sys.stdin.isatty():raise RuntimeError("interactive_terminal_required")
 print("Existing Telegram bot token (input hidden). Do not paste token into ChatGPT.",flush=True)
 token=getpass.getpass("Existing TELEGRAM_BOT_TOKEN: ").strip()
 if not TOKEN_PATTERN.fullmatch(token):raise RuntimeError("token_format_invalid")
 result=verify(token,"operator_hidden_input",pre)
 write_secret(token)
 status("EXISTING_BOT_TOKEN_READY",source="operator_hidden_input",channel=result["channel_username"],
        bot_username=result["bot_username"],bot_can_post=True,
        secret_file="RG_SECRETS/rg_telegram_bot_token",permissions="0600",
        no_message_sent=True,legacy_cloudflare_unchanged=True)
if __name__=="__main__":
 try:main()
 except Exception as ex:
  message=str(ex)
  # Block secret leakage through exception strings.
  allowed={"preflight_module_missing","bot_not_channel_posting_admin",
           "target_symlink_refused","secret_directory_symlink_refused",
           "interactive_terminal_required","token_format_invalid","sudo_required"}
  reason=message if message in allowed else type(ex).__name__
  status("BLOCKED",reason=reason,production_post_enabled=False)
  sys.exit(1)
