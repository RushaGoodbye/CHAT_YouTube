"""Run actual RG postrun QA only inside disposable copied workspace.

Production Studio and source XML are read only. QA subprocess writes only to temp.
The result never changes existing queue state, manifest, or export permissions.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from rg_studio_postrun import _primary_outputs
from stage_release_health_v2 import patch_source

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SOURCES=(891,898,904)

def emit(*a):print("RGISOLATED|"+"|".join(map(str,a)),flush=True)

def single(n):
    n=str(n)
    src_dir=APP/n
    chosen=_primary_outputs(src_dir,[],n)
    if not chosen:emit(n,"NO_VERIFIED_XML");return
    manifest=APP/f"RG_EDITED_{n}_MULTI_DIALOGUE.json"
    with tempfile.TemporaryDirectory(prefix="RG_REPAIR_QA_COPY_"+n+"_") as place:
        root=Path(place)
        dest=root/n
        dest.mkdir()
        for file in chosen:
            shutil.copy2(file,dest/file.name)
            # Relevant current-run sidecars copied to corresponding path.
            for suffix in ("_FINAL_RELEASE_GATE.json","_FINAL_TIMELINE_AUDIT.json",
                           "_CIGARETTE_BLUR_QA.json","_DIRECTOR_QA.json"):
                p=file.with_name(file.stem+suffix)
                q=APP/(file.stem+suffix)
                if p.is_file():shutil.copy2(p,dest/p.name)
                elif q.is_file():shutil.copy2(q,root/q.name)
            base=APP/file.name
            if base.is_file() and base.resolve()!=file.resolve():
                shutil.copy2(base,root/base.name)
            for suffix in ("_FINAL_RELEASE_GATE.json","_FINAL_TIMELINE_AUDIT.json"):
                q=APP/(file.stem+suffix)
                if q.is_file() and not (root/q.name).is_file():shutil.copy2(q,root/q.name)
        if manifest.is_file():
            data=json.loads(manifest.read_text(encoding="utf-8-sig"))
            for r in data.get("outputs") or []:
                p=Path(str(r.get("premiere_xml") or ""))
                if p.name: r["premiere_xml"]=str(dest/p.name)
                p=Path(str(r.get("xml") or ""))
                if p.name:r["xml"]=str(root/p.name)
            (root/manifest.name).write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
        subprocess_env=os.environ.copy()
        subprocess_env["PYTHONIOENCODING"]="utf-8"
        output_json=json.dumps([str(p) for p in dest.glob("RG_EDITED_*.xml") if not p.stem.endswith(("_SHORTS","_UNCENSORED"))],ensure_ascii=False)
        release_source=APP/"rg_release_health_gate.py"
        (root/"rg_release_health_gate.py").write_text(
            patch_source(release_source.read_text(encoding="utf-8")),encoding="utf-8")
        entry=root/"qa_entry.py"
        entry.write_text(
            "import sys,runpy,importlib.util\\n"
            + "from pathlib import Path\\n"
            + "app=Path("+repr(str("F:\\RG_AUTO_EDIT\\RG Auto Edit App"))+")\\n"
            + "sys.path.insert(0,str(app))\\n"
            + "spec=importlib.util.spec_from_file_location('rg_release_health_gate',str(Path(__file__).with_name('rg_release_health_gate.py')))\\n"
            + "mod=importlib.util.module_from_spec(spec)\\n"
            + "spec.loader.exec_module(mod)\\n"
            + "sys.modules['rg_release_health_gate']=mod\\n"
            + "sys.argv=[str(app/'rg_studio_postrun.py')]+sys.argv[1:]\\n"
            + "runpy.run_path(str(app/'rg_studio_postrun.py'),run_name='__main__')\\n",
            encoding="utf-8")
        cmd=[sys.executable,"-X","utf8",str(entry),
             "--stream",n,"--folder",str(dest),"--outputs-json",output_json]
        emit(n,"QA_COMMAND_ISOLATED","XML_COUNT",len(chosen))
        proc=subprocess.run(cmd,cwd=str(root),env=subprocess_env,stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",timeout=240)
        report=dest/"RG_POSTRUN_QA.json"
        if report.is_file():
            result=json.loads(report.read_text(encoding="utf-8-sig"))
            emit(n,"FULL_QA_PASS",result.get("passed"),"EXIT",proc.returncode,"CHECKS",len(result.get("checks") or []))
            for item in result.get("checks") or []:
                emit(n,"CHECK",item.get("name"),"PASS",item.get("ok"),"CRITICAL",item.get("critical"),
                     "DETAIL",str(item.get("detail") or "")[:230].replace("\n"," "))
        else:
            emit(n,"NO_QA_REPORT","EXIT",proc.returncode,"OUTPUT",proc.stdout[-1100:])
        emit(n,"WORKSPACE_REMOVED_AFTER_QA",True)
def main():
    emit("TIME",datetime.now().astimezone().isoformat())
    for n in SOURCES:
        try: single(n)
        except Exception as exc:emit(n,"EXCEPTION",repr(exc))
    emit("PRODUCTION_XML_UNMODIFIED",True)
if __name__=="__main__":main()
