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
    print("RG_904_RESUME_BUTTON_READONLY_DIAG")
    print(json.dumps({"schema":"RG_904_RESUME_BUTTON_READONLY_V1","studio_version":text(APP/"rg_studio_version.py").splitlines()[:2],"ui":u,"multi":m,"manifest":meta,"log_tail":tail,"processes":procs,"mutated":False},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
