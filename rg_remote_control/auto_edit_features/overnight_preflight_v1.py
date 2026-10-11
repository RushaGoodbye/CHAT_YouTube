#!/usr/bin/env python3
# Read-only RG Auto Edit night batch readiness check.
from __future__ import annotations
import ast, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
LOCAL=Path(os.environ.get("LOCALAPPDATA",""))/"RG_Auto_Edit"
QUEUE=LOCAL/"studio_batch_queue.json"
TARGETS=[str(s) for s in (json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("args") or {}).get("streams",[])] if len(sys.argv)>1 else []
def read_json(p):
    try:return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:return {"error":type(e).__name__,"exists":p.is_file()}
def stat_file(p):
    try:
        st=p.stat();return {"exists":True,"bytes":st.st_size,"modified":round(st.st_mtime)}
    except FileNotFoundError:return {"exists":False}
    except Exception as e:return {"error":repr(e)}
def cmd(args,timeout=15):
    try:
        p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",errors="replace",timeout=timeout,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        return {"exit":p.returncode,"stdout":p.stdout[-10000:],"stderr":p.stderr[-1000:]}
    except Exception as e:return {"error":str(e)[:300]}
out={"schema":"RG_OVERNIGHT_PREFLIGHT_V1","timestamp":time.time(),"read_only":True,"targets":TARGETS}
out["version"]=(APP/"rg_studio_version.py").read_text(encoding="utf-8-sig",errors="replace").splitlines()[:4] if (APP/"rg_studio_version.py").is_file() else None
out["queue"]=read_json(QUEUE)
out["modules"]={}
for n in ("rg_studio_ui.py","rg_studio_main.py","rg_studio_postrun.py","rg_multi_dialogue.py","rg_auto_edit_one_button.py","rg_server_resolver.py","rg_final_compilation.py"):
    p=APP/n
    try:
        source=p.read_text(encoding="utf-8-sig")
        ast.parse(source,filename=n)
        out["modules"][n]={"syntax":"PASS","bytes":p.stat().st_size}
    except Exception as e:out["modules"][n]={"syntax":"FAIL","error":str(e)[:200]}
out["runtime"]=stat_file(Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe"))
out["disks"]={}
for drive in ("F:\\","D:\\","C:\\"):
    try:
        d=shutil.disk_usage(drive)
        out["disks"][drive]={"free_gb":round(d.free/2**30,1),"total_gb":round(d.total/2**30,1)}
    except Exception as e:out["disks"][drive]={"error":str(e)[:100]}
out["processes"]=cmd(["powershell","-NoProfile","-NonInteractive","-Command",r"$p=Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -and ($_.CommandLine -match 'rg_studio_main|rg_auto_edit_one_button|rg_multi_dialogue|rg_production_wrapper|rg_studio_update|rg_auto_edit.*python')}; $p | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress -Depth 3"],timeout=20)
out["gpu"]=cmd(["nvidia-smi","--query-gpu=name,memory.free,memory.total,utilization.gpu,temperature.gpu","--format=csv,noheader,nounits"],timeout=10)
out["sleep"]=cmd(["powercfg","/query","SCHEME_CURRENT","SUB_SLEEP","STANDBYIDLE"],timeout=10)
out["update_state"]=read_json(DATA/"update_supervisor_state.json")
out["inputs"]={}
candidate_roots={}
for base in (APP,DATA,LOCAL):
    for name in ("rg_auto_edit_config.json","studio_settings.json","rg_studio_settings.json","settings.json","ui_state.json","studio_config.json"):
        p=base/name
        if not p.is_file():continue
        data=read_json(p)
        if isinstance(data,dict):
            for k,v in data.items():
                if re.search(r"(video|audio|screen|folder|root|source|output).*",str(k),re.I) and isinstance(v,str) and len(v)<320:
                    candidate_roots[k]=v
out["configured_paths"]=candidate_roots
# Only resolve user-supplied numbers or existing queued stream; no scans of whole NAS.
queue=out["queue"] if isinstance(out["queue"],dict) else {}
streams=list(dict.fromkeys(TARGETS or queue.get("queue",[])))
for st in streams[:25]:
    if not re.fullmatch(r"\d{3,5}",str(st)):continue
    row={"stream":st,"result_dir":stat_file(APP/str(st)),"run_log":stat_file(APP/"run_manifests"/str(st)/"STUDIO_RUN.log")}
    for kind,ext in (("video",".mp4"),("audio",".mp3")):
        roots=[v for k,v in candidate_roots.items() if kind in k.lower() and isinstance(v,str)]
        row[kind+"_candidates"]=[{"file":str(Path(root)/(str(st)+ext)),"exists":(Path(root)/(str(st)+ext)).is_file()} for root in roots[:5]]
    out["inputs"][st]=row
out["checks"]={
"queue_not_empty":bool(queue.get("queue")),
"queue_running":bool(queue.get("running")),
"stale_failed_rows":[r.get("stream") for r in queue.get("rows",[]) if r.get("status")=="ПОМИЛКА"],
"module_syntax_ok":all(x.get("syntax")=="PASS" for x in out["modules"].values()),
"runtime_exists":out["runtime"].get("exists") is True,
"data_free_gb":out["disks"].get("F:\\",{}).get("free_gb"),
}
print("RG_OVERNIGHT_PREFLIGHT|"+json.dumps(out,ensure_ascii=False,default=str),flush=True)
