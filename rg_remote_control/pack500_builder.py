from __future__ import annotations
import hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile,py_compile
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNTIME_PY=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
ROOT=Path(__file__).resolve().parent
PACK400=ROOT/"releases"/"pack400"/"INSTALL_PACK400.py"
REL=ROOT/"releases"/"pack500"/"rg_pack500_reliability.py"
BODY=ROOT/"releases"/"pack500"/"INSTALL_PACK500_BODY.py.txt"
NOTES=ROOT/"releases"/"pack500"/"RELEASE_NOTES_PACK500.txt"
MATRIX=ROOT/"releases"/"pack500"/"PACK500_FEATURE_MATRIX.json"
VERSION="0.20.9.0";PACK="PACK500"
NAME=f"RG_AUTO_EDIT_STUDIO_UPDATE_{VERSION}_{PACK}_RELIABILITY_PERFORMANCE_1-50.zip"

def _sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def build_auto_edit_pack500_update()->dict:
    if os.name!="nt":raise RuntimeError("Windows only")
    if not APP.is_dir():raise RuntimeError("RG Auto Edit app not found")
    for p in (PACK400,REL,BODY,NOTES,MATRIX):
        if not p.is_file():raise RuntimeError("PACK500 source missing: "+str(p))

    base=PACK400.read_text(encoding="utf-8")
    rel=REL.read_text(encoding="utf-8")
    body=BODY.read_text(encoding="utf-8")
    installer="from __future__ import annotations\nBASE_INSTALLER="+repr(base)+"\nPACK500_RELIABILITY="+repr(rel)+"\n"+body

    downloads=Path.home()/"Downloads";downloads.mkdir(parents=True,exist_ok=True)
    packages=DATA/"PACKAGES";packages.mkdir(parents=True,exist_ok=True)
    zip_path=downloads/NAME;nas_copy=packages/NAME

    with tempfile.TemporaryDirectory(prefix="rg_pack500_build_") as td:
        td=Path(td);root=td/"RG_PACK500";root.mkdir()
        inst=root/"INSTALL_PACK500.py";inst.write_text(installer,encoding="utf-8")
        rn=root/"RELEASE_NOTES_PACK500.txt";shutil.copy2(NOTES,rn)
        mx=root/"PACK500_FEATURE_MATRIX.json";shutil.copy2(MATRIX,mx)

        # Exact copy of the current live app. Running backend is never modified.
        dry=td/"dry_app";shutil.copytree(APP,dry,dirs_exist_ok=True)
        env=os.environ.copy();env.update({"RG_PACK500_DRYRUN":"1","RG_PACK400_DRYRUN":"1","PYTHONUTF8":"1","PYTHONIOENCODING":"utf-8"})
        cp=subprocess.run([sys.executable,"-X","utf8",str(inst)],cwd=str(dry),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=360)
        if cp.returncode!=0 or "PACK500_INSTALL|PASS" not in (cp.stdout or ""):
            raise RuntimeError("PACK500 dry-run failed: "+(cp.stdout or "")[-20000:]+(cp.stderr or "")[-20000:])

        targets=["rg_studio_ui.py","rg_multi_dialogue.py","rg_pack500_reliability.py","rg_pack500_selftest.py","rg_studio_version.py"]
        for n in targets:py_compile.compile(str(dry/n),doraise=True)

        smoke_py=str(RUNTIME_PY if RUNTIME_PY.is_file() else Path(sys.executable))
        pe={**env,"QT_QPA_PLATFORM":"offscreen","RG_AUTO_EDIT_BACKEND":str(dry)}
        sm=subprocess.run([smoke_py,"-X","utf8","-c","import rg_pack500_reliability,rg_multi_dialogue,rg_studio_ui;print('PACK500_IMPORT_OK')"],
                          cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=140)
        if sm.returncode!=0 or "PACK500_IMPORT_OK" not in (sm.stdout or ""):
            raise RuntimeError("PACK500 import smoke failed: "+(sm.stdout or "")[-14000:]+(sm.stderr or "")[-14000:])

        st=subprocess.run([smoke_py,"-X","utf8",str(dry/"rg_pack500_selftest.py")],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
        if st.returncode!=0 or "READY FOR PRODUCTION" not in (st.stdout or ""):
            raise RuntimeError("PACK500 selftest failed: "+(st.stdout or "")[-16000:]+(st.stderr or "")[-16000:])

        probe=dry/"_pack500_ui_probe.py"
        probe.write_text("""import os,json
os.environ["QT_QPA_PLATFORM"]="offscreen";os.environ["RG_AUTO_EDIT_BACKEND"]=os.getcwd();os.environ["RG_PACK500_DRYRUN"]="1"
from PySide6.QtWidgets import QApplication
from rg_studio_ui import StudioWindow
app=QApplication([]);w=StudioWindow();w.resize(1920,1080);w.show()
for _ in range(6):app.processEvents()
ui=open("rg_studio_ui.py",encoding="utf-8").read()
ok=(w.tabs.count()>0 and "RG_PACK500_CONTROL_CENTER_UI" in ui and "def _pack500_try_install_pending_update" in ui and "RG_PACK500_PROCESS_OWNERSHIP" in ui)
print("PACK500_UI_PROBE|"+json.dumps({"passed":ok,"tabs":w.tabs.count()},ensure_ascii=False))
raise SystemExit(0 if ok else 7)
""",encoding="utf-8")
        up=subprocess.run([smoke_py,"-X","utf8",str(probe)],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=140)
        if up.returncode!=0 or "PACK500_UI_PROBE|" not in (up.stdout or ""):
            raise RuntimeError("PACK500 UI probe failed: "+(up.stdout or "")[-14000:]+(up.stderr or "")[-14000:])

        itxt=inst.read_text(encoding="utf-8")
        if "PACK500_UPDATE_LOCK|ACTIVE_BACKEND" not in itxt or "active_backend_processes()" not in itxt:
            raise RuntimeError("OS update-lock gate missing")

        matrix=json.loads(mx.read_text(encoding="utf-8"))
        if int((matrix.get("coverage") or {}).get("count") or 0)!=50:raise RuntimeError("feature matrix != 50")

        files=[]
        for p in (inst,rn,mx):files.append({"path":p.name,"sha256":_sha(p),"size":p.stat().st_size})
        manifest={"schema":"RG_UPDATE_MANIFEST_V2","product":"RG Auto Edit Studio","studio_version":VERSION,"channel":"STABLE",
          "summary":"PACK500 Reliability + Performance 1-50 (cumulative PACK400 + PACK500)","created_at":"2026-10-06",
          "files":files,"coverage":{"from":1,"to":50,"count":50},"core_modified":True,"ui_only":False,"expected_ui_change":True,
          "base":"embedded PACK400 + current live Studio",
          "safety":{"installed_during_build":False,"active_stream_touched":False,"os_update_lock":True,"dry_run_current_copy":True,
                    "compile_gate":True,"import_smoke":True,"ui_probe":True,"feature_matrix_gate":True,"rollback":True,
                    "original_source_direct_locked":True,"audio_processing_policy_unchanged":True}}
        mf=root/"RG_UPDATE_MANIFEST.json";mf.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in root.iterdir():zz.write(p,p.name)

    shutil.copy2(zip_path,nas_copy)
    with zipfile.ZipFile(zip_path) as zz:
        bad=zz.testzip()
        if bad:raise RuntimeError("ZIP CRC failure: "+bad)
        m=json.loads(zz.read("RG_UPDATE_MANIFEST.json").decode("utf-8"))
        for row in m["files"]:
            b=zz.read(row["path"])
            if hashlib.sha256(b).hexdigest()!=row["sha256"] or len(b)!=row["size"]:raise RuntimeError("manifest mismatch "+row["path"])
        mx=json.loads(zz.read("PACK500_FEATURE_MATRIX.json").decode("utf-8"))
        if int((mx.get("coverage") or {}).get("count") or 0)!=50:raise RuntimeError("feature matrix mismatch")

    return {"status":"READY","version":VERSION,"pack":PACK,"coverage":"1-50","zip":str(zip_path),"nas_copy":str(nas_copy),
            "size":zip_path.stat().st_size,"sha256":_sha(zip_path),"installed":False,"active_stream_touched":False,
            "cumulative_pack400":True,"os_update_lock":"PASS","dry_run_current_live_copy":"PASS","compile":"PASS",
            "import_smoke":"PASS","ui_probe":"PASS","selftest":"READY FOR PRODUCTION","feature_matrix":"50/50","crc":"PASS","manifest":"PASS"}
