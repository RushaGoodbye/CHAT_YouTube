#!/usr/bin/env python3
"""RG Telegram NAS stage-bundle v1. Safe offline staging; NEVER sends Telegram or deploys Cloudflare."""
import argparse, datetime, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, urllib.request
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE")
BASE="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube"
MODULES={
 "rg_telegram_nas_shadow_store_v1.py":"e9ad3c76933499b5b4a71c04dc7d704143684a40",
 "rg_telegram_shadow_queue_v1.py":"079dc0d8a517cc349ee3da2bd942a9103449b306",
 "rg_telegram_nas_event_intake_v1.py":"acfd3c983a04e89caef2f73d7343831a0dc21ef0",
 "rg_telegram_shadow_file_bridge_v1.py":"b64b637ebefae0f73f5d724fdf8b5f7edfa68948",
 "rg_telegram_shadow_observer_v1.py":"22ad1d8f51afead50873eb19612aafa92d85f682",
 "rg_telegram_import_minute_watchdog_shadow_v1.py":"5538d209569cad20b44549270ec88dc73e786837",
 "rg_telegram_kyiv_alert_shadow_fsm_v1.py":"0499158da716247c38bb43bdb783bd63d9b37d78"
}
def run(args,**opts):
    return subprocess.run(args,check=True,text=True,capture_output=True,timeout=55,**opts)
def stage(folder):
    out=[]
    for name,sha in MODULES.items():
        url=f"{BASE}/{sha}/rg_remote_control/nas/{name}"
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"RG-NAS-Migration/1.0"}),timeout=15) as response:
            source=response.read(250001)
        if not source or len(source)>250000:raise RuntimeError(f"Source missing/oversize: {name}")
        p=folder/name
        p.write_bytes(source)
        run([sys.executable,"-m","py_compile",str(p)])
        out.append({"name":name,"sha256":hashlib.sha256(source).hexdigest()})
    # Stage 1 init and test in an isolated temp DB; never touch live Telegram or existing state here.
    for name in MODULES:
        if name=="rg_telegram_shadow_observer_v1.py" or name=="rg_telegram_import_minute_watchdog_shadow_v1.py":
            # The observer's sample and import commands touch NAS state; never invoke here.
            pass
        if name=="rg_telegram_nas_shadow_store_v1.py" or name=="rg_telegram_shadow_queue_v1.py" or name=="rg_telegram_nas_event_intake_v1.py" or name=="rg_telegram_shadow_file_bridge_v1.py" or name=="rg_telegram_kyiv_alert_shadow_fsm_v1.py":
            kwargs={"timeout":55}
            if name=="rg_telegram_shadow_file_bridge_v1.py":
                command=[sys.executable,str(folder/name),"selftest","--intake",str(folder/"rg_telegram_nas_event_intake_v1.py")]
            else: command=[sys.executable,str(folder/name),"selftest"]
            run(command,**kwargs)
    return out
def install(root,folder):
    backup=root/("bundle-backup-"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(parents=True,exist_ok=False)
    installed=[]
    try:
        for name in MODULES:
            src=folder/name;dst=root/name
            if dst.exists():
                if dst.is_symlink():raise RuntimeError(f"Symlink target refused: {name}")
                shutil.copy2(dst,backup/name)
            tmp=root/("."+name+".new")
            shutil.copy2(src,tmp)
            os.replace(tmp,dst)
            installed.append(name)
        # initialize only additive, pre-existing SQLite schema preserved
        run([sys.executable,str(root/"rg_telegram_nas_shadow_store_v1.py"),"initialize"])
        run([sys.executable,str(root/"rg_telegram_shadow_queue_v1.py"),"initialize"])
        run([sys.executable,str(root/"rg_telegram_nas_event_intake_v1.py"),"initialize"])
        run([sys.executable,str(root/"rg_telegram_shadow_file_bridge_v1.py"),"initialize"])
        run([sys.executable,str(root/"rg_telegram_shadow_file_bridge_v1.py"),"status"])
    except Exception:
        for name in reversed(installed):
            dst=root/name;old=backup/name
            if old.exists():shutil.copy2(old,dst)
            else:dst.unlink(missing_ok=True)
        raise
    return str(backup)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["selftest","install","status"])
    p.add_argument("--root",default=str(ROOT))
    a=p.parse_args();root=pathlib.Path(a.root)
    if a.mode=="status":
        print(json.dumps({"status":"READY" if (root/"migration_shadow.sqlite3").is_file() else "NOT_INITIALIZED","modules_present":{n:(root/n).is_file() for n in MODULES},"sending_enabled":False,"cloudflare_deploy":False},ensure_ascii=False));return
    with tempfile.TemporaryDirectory(prefix="rg-telegram-bundle-") as td:
        folder=pathlib.Path(td)
        manifest=stage(folder)
        if a.mode=="selftest":
            print(json.dumps({"status":"SELFTEST_PASS","modules_tested":len(manifest),"install":False,"telegram_calls":0,"cloudflare_calls":0}));return
        root.mkdir(parents=True,exist_ok=True)
        backup=install(root,folder)
    print(json.dumps({"status":"INSTALLED_SHADOW_ONLY","modules":len(MODULES),"backup":backup,"publishing_enabled":False,"cloudflare_deploy":False},ensure_ascii=False))
if __name__=="__main__":
    try:main()
    except Exception as e:
        print(json.dumps({"status":"FAILED","error":str(e)[:180],"sending_enabled":False}),file=sys.stderr)
        sys.exit(1)
