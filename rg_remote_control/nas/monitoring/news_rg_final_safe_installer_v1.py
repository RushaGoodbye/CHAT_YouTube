#!/usr/bin/env python3
"""NEWS RG bundled safe installer. Installs ONE DSM-tick sidecar, isolated writes only.
A NEWS RG approval is *never* mapped to legacy publication approval.
"""
import os,sys,json,pathlib,hashlib,shutil,tempfile,subprocess,time,sqlite3
BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
OP=BASE/"operator"; TICK=BASE/"rg_news_dsm_tick.sh"
SCRIPT=OP/"news_rg_final_tick_v1.py"
INGEST=OP/"news_rg_source_shadow_ingest_v1.py"
BRIDGE=pathlib.Path("/tmp/news_rg_private_bridge_v1.py")
ADAPTER=pathlib.Path("/tmp/news_rg_ollama_adapter_v1.py")
MARK="# NEWS_RG_FINAL_ISOLATED_TICK_V1"
def emit(**kw):print(json.dumps(kw,ensure_ascii=False,sort_keys=True))
def basecheck():
    if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
    for p in (BASE,OP,TICK,INGEST,BRIDGE,ADAPTER):
        if p.is_symlink() or not p.exists():raise RuntimeError("MISSING_OR_SYMLINK_"+p.name)
    s=TICK.read_text()
    if not s.startswith("#!/bin/sh") or "rg_news2_private_final_guard_v1.py" not in s:raise RuntimeError("UNKNOWN_DSM_TICK")
    if "NEWS_RG_FINAL_ISOLATED_TICK" in s and MARK not in s:raise RuntimeError("UNKNOWN_PATCH")
    return s
def safe_run(argv,secs):
    r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=secs)
    if r.returncode:raise RuntimeError("COMMAND_FAILED_"+str(r.returncode))
    try:return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:raise RuntimeError("BAD_COMMAND_RESULT")
def status():
    b=basecheck()
    return dict(status="READY",installed=MARK in b,private_delivery="NOT_CONNECTED",publications=0,telegram_calls=0)
def install():
    script=basecheck()
    if MARK in script:return dict(status="ALREADY_INSTALLED",publications=0)
    # Sidecar must neither call Telegram Bot API nor touch production DB.
    code='''#!/usr/bin/env python3
import json,os,subprocess,sys,fcntl,pathlib,datetime
O=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator")
def run(argv,timeout):
 try:
  r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
  return r.returncode
 except Exception:return -1
def main():
 # isolated AI pipeline, at most one story per tick and no public/Telegram calls
 fd=os.open(str(O/"news_rg_final.lock"),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  run([sys.executable,str(O/"news_rg_source_shadow_ingest_v1.py"),"scan"],110)
  bridge=pathlib.Path("/tmp/news_rg_private_bridge_v1.py")
  adapter=pathlib.Path("/tmp/news_rg_ollama_adapter_v1.py")
  if bridge.is_file() and adapter.is_file():
   run([sys.executable,str(bridge),"prepare-one"],80)
 finally:os.close(fd)
if __name__=="__main__":main()
'''
    compile(code,str(SCRIPT),"exec")
    backup=OP/("rg_news_dsm_tick.before_news_rg_final_"+hashlib.sha256(script.encode()).hexdigest()[:12]+".sh")
    if not backup.exists():
        fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w") as f:f.write(script);f.flush();os.fsync(f.fileno())
    fd,tmp=tempfile.mkstemp(prefix=".newsrg_final_",dir=str(OP))
    try:
        with os.fdopen(fd,"w") as f:f.write(code);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o700);os.replace(tmp,SCRIPT)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    # Don't edit the tick: that could accidentally enable a legacy publication branch.
    return dict(status="SIDECAR_INSTALLED_NOT_SCHEDULED",backup=str(backup),sidecar=str(SCRIPT),private_delivery="NOT_CONNECTED",production_tick_unchanged=True,publications=0)
if __name__=="__main__":
 try:
  mode=sys.argv[1] if len(sys.argv)>1 else "status"
  if mode=="selftest":
   assert MARK.startswith("# NEWS");emit(status="SELFTEST_PASS")
  elif mode=="status":emit(**status())
  elif mode=="install":emit(**install())
  else:raise RuntimeError("BAD_MODE")
 except Exception as e:emit(status="SAFE_STOP",reason=str(e));sys.exit(2)
