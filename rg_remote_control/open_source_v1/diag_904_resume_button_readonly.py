#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only inspection of 904 resume button wiring and production runtime."""
from pathlib import Path
import ast,json,os,re,subprocess,datetime
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
LOCAL=Path(os.getenv("LOCALAPPDATA") or str(Path.home()))
def text(path):
    return path.read_text(encoding="utf-8-sig",errors="replace") if path.is_file() else ""
def around(rows,idx,before=5,after=12):
    return "\n".join(f"{i+1}: {rows[i]}" for i in range(max(idx-before,0),min(idx+after,len(rows))))
def scan_code(name,queries,maxhits=65):
    path=APP/name
    s=text(path);rows=s.splitlines()
    hits=[]
    for i,line in enumerate(rows):
        if any(re.search(q,line,re.I) for q in queries):
            hits.append({"line":i+1,"snippet":around(rows,i)})
            if len(hits)>=maxhits:break
    functions=[]
    try:
        parsed=ast.parse(s,filename=name)
        for node in ast.walk(parsed):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and any(q in node.name.lower() for q in ("resume","continue","preflight","start_single","run_backend","launch")):
                functions.append({"name":node.name,"line":node.lineno,"source":"\n".join(f"{j+1}: {rows[j]}" for j in range(node.lineno-1,min(len(rows),node.end_lineno if node.end_lineno and node.end_lineno-node.lineno<110 else node.lineno+80)))})
    except Exception as exc:
        functions=[{"parse_error":str(exc)}]
    return {"file":name,"present":path.is_file(),"length":len(s),"hits":hits,"functions":functions}
def main():
    u=scan_code("rg_studio_ui.py",[
        r"ПРОДОВЖИТИ",r"resume",r"continue",r"clicked.connect",r"start_single",r"def _preflight",r"rg_multi_dialogue"],80)
    st=scan_code("rg_studio_state.py",[r"def load_state",r"def update_state",r"status",r"state_file"],35)
    m=scan_code("rg_multi_dialogue.py",[r"resume",r"can_resume",r"RG_RESUME_PROTECT_PREFIX",r"revision_output_path",r"resume_rows"],32)
    p=APP/"RG_EDITED_904_MULTI_DIALOGUE.json"; meta={}
    if p.is_file():
        j=json.loads(text(p))
        meta={"exists":True,"status":j.get("status"),"failed_dialogue":j.get("failed_dialogue"),"count":j.get("dialogue_count"),
              "completed":len(j.get("outputs") or []),"outputs":[{"index":x.get("index"),"name":Path(x.get("xml","")).name,"exists":Path(x.get("xml","")).is_file(),"job_key":x.get("job_key")} for x in (j.get("outputs") or [])],
              "mtime":datetime.datetime.fromtimestamp(p.stat().st_mtime,datetime.timezone.utc).isoformat()}
    log=APP/"run_manifests"/"904"/"STUDIO_RUN.log"
    tail=text(log).splitlines()[-35:]
    # Process list: read-only Windows CIM; don't inspect secret environment or tokens.
    procs=[]
    try:
        cp=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",
         "Get-CimInstance Win32_Process | Where-Object { ($_.Name -in @('python.exe','pythonw.exe')) -and ($_.CommandLine -match 'rg_studio|rg_multi_dialogue|rg_production_wrapper') } | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"],
         capture_output=True,text=True,timeout=20)
        j=json.loads(cp.stdout) if cp.stdout.strip() else []
        for x in (j if isinstance(j,list) else [j]):
            procs.append({"pid":x.get("ProcessId"),"name":x.get("Name"),"command_tail":str(x.get("CommandLine"))[-320:]})
    except Exception as exc:procs=[{"error":str(exc)}]
    resume_state_files=[]
    state_candidates=[
        APP/"run_manifests"/"904"/"STUDIO_STATE.json",
        APP/"run_manifests"/"904"/"RUN_STATE.json",
        APP/"run_manifests"/"904"/"RG_STUDIO_RUN_STATE.json",
        LOCAL/"RG_AUTO_EDIT"/"run_state"/"904"/"RUN_STATE.json",
        LOCAL/"RG_AUTO_EDIT"/"904"/"state.json",
        LOCAL/"RG_AUTO_EDIT"/"studio_run_state"/"904.json",
        LOCAL/"RG_Auto_Edit"/"904"/"state.json",
    ]
    for f in state_candidates:
        if f.is_file():
            resume_state_files.append({"path":str(f),"value":text(f)[:4000]})
    uifile=APP/"rg_studio_ui.py"
    uirows=text(uifile).splitlines()
    specific={}
    for q in ["from rg_studio_state import", "load_state(", "def _start_stream", "def _backend_finished",
              "def _start_postrun_qa", "def _refresh_resume_state", "def resume_incomplete_run", "def _on_finished"]:
        locs=[i for i,row in enumerate(uirows) if q in row]
        specific[q]=[around(uirows,i,4,32) for i in locs[:4]]

    state_imports=[]
    try:
        tree=ast.parse(text(APP/"rg_studio_ui.py"))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                if any(x.name in ("load_state","recovery_plan","update_state") for x in node.names):
                    state_imports.append({"module":node.module,"symbols":[x.name for x in node.names]})
    except Exception as e:state_imports=[{"error":str(e)}]
    state_inspection={}
    for x in state_imports:
        module=x.get("module")
        if module:
            path=APP/(module.replace(".","/")+".py")
            code=text(path)
            state_inspection[module]={"path":str(path),"has_file":path.is_file(),
                 "headers":code.splitlines()[:25],
                 "hits":[around(code.splitlines(),i,3,18)
                         for i,line in enumerate(code.splitlines())
                         if "def load_state" in line or "def recovery_plan" in line or "STATE" in line][:22]}
    specific["def _start_stream_full"]=[around(uirows,i,4,105) for i,row in enumerate(uirows) if "def _start_stream(self,stream):" in row]
    specific["def _start_service_process"]=[around(uirows,i,4,54) for i,row in enumerate(uirows) if "def _start_service_process" in row]
    print("RG_904_RESUME_BUTTON_READONLY_DIAG")
    print(json.dumps({"schema":"RG_904_RESUME_BUTTON_READONLY_V1","studio_version":text(APP/"rg_studio_version.py").splitlines()[:2],"ui":u,"multi":m,"state_module":st,"manifest":meta,"log_tail":tail,"processes":procs,"ui_specific":specific,"state_file_candidates":resume_state_files,"state_imports":state_imports,"state_inspection":state_inspection,"mutated":False},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
