from __future__ import annotations
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,zipfile,py_compile
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNTIME_PY=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
ROOT=Path(__file__).resolve().parent
RELEASE=ROOT/"releases"/"pack400"
VERSION="0.20.8.0"
PACK="PACK400"
NAME=f"RG_AUTO_EDIT_STUDIO_UPDATE_{VERSION}_{PACK}_PRODUCTIVITY_1-50.zip"

def _sha(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def build_auto_edit_pack400_update()->dict:
    if os.name!="nt":raise RuntimeError("Windows only")
    if not APP.is_dir():raise RuntimeError("RG Auto Edit app not found")
    installer_src=RELEASE/"INSTALL_PACK400.py"
    notes_src=RELEASE/"RELEASE_NOTES_PACK400.txt"
    matrix_src=RELEASE/"PACK400_FEATURE_MATRIX.json"
    for p in (installer_src,notes_src,matrix_src):
        if not p.is_file():raise RuntimeError("release source missing: "+str(p))

    downloads=Path.home()/"Downloads";downloads.mkdir(parents=True,exist_ok=True)
    packages=DATA/"PACKAGES";packages.mkdir(parents=True,exist_ok=True)
    zip_path=downloads/NAME
    nas_copy=packages/NAME

    with tempfile.TemporaryDirectory(prefix="rg_pack400_build_") as td:
        td=Path(td);root=td/"RG_PACK400";root.mkdir()
        inst=root/"INSTALL_PACK400.py";shutil.copy2(installer_src,inst)
        notes=root/"RELEASE_NOTES_PACK400.txt";shutil.copy2(notes_src,notes)
        matrix=root/"PACK400_FEATURE_MATRIX.json";shutil.copy2(matrix_src,matrix)

        # Exact current live app copy. The running Studio/backend are read-only sources here.
        dry=td/"dry_app";shutil.copytree(APP,dry,dirs_exist_ok=True)
        env=os.environ.copy();env["RG_PACK400_DRYRUN"]="1";env["PYTHONUTF8"]="1";env["PYTHONIOENCODING"]="utf-8"
        cp=subprocess.run([sys.executable,"-X","utf8",str(inst)],cwd=str(dry),env=env,
                          capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=240)
        if cp.returncode!=0 or "PACK400_INSTALL|PASS" not in (cp.stdout or ""):
            raise RuntimeError("PACK400 dry-run failed: "+(cp.stdout or "")[-16000:]+(cp.stderr or "")[-16000:])

        for n in ["rg_studio_ui.py","rg_multi_dialogue.py","rg_pack400_productivity.py","rg_pack400_selftest.py","rg_studio_version.py"]:
            py_compile.compile(str(dry/n),doraise=True)

        smoke_py=str(RUNTIME_PY if RUNTIME_PY.is_file() else Path(sys.executable))
        pe={**env,"QT_QPA_PLATFORM":"offscreen","RG_AUTO_EDIT_BACKEND":str(dry)}
        sm=subprocess.run([smoke_py,"-X","utf8","-c",
                           "import rg_pack400_productivity,rg_multi_dialogue,rg_studio_ui;print('PACK400_IMPORT_OK')"],
                          cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=100)
        if sm.returncode!=0 or "PACK400_IMPORT_OK" not in (sm.stdout or ""):
            raise RuntimeError("PACK400 import smoke failed: "+(sm.stdout or "")[-10000:]+(sm.stderr or "")[-10000:])

        st=subprocess.run([smoke_py,"-X","utf8",str(dry/"rg_pack400_selftest.py")],
                          cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=90)
        if st.returncode!=0 or "READY FOR PRODUCTION" not in (st.stdout or ""):
            raise RuntimeError("PACK400 selftest failed: "+(st.stdout or "")[-12000:]+(st.stderr or "")[-12000:])

        # Lightweight UI construction gate, no backend/process start.
        probe=dry/"_pack400_ui_probe.py"
        probe.write_text("""import os,json
os.environ["QT_QPA_PLATFORM"]="offscreen";os.environ["RG_AUTO_EDIT_BACKEND"]=os.getcwd()
from PySide6.QtWidgets import QApplication
from rg_studio_ui import StudioWindow
app=QApplication([]);w=StudioWindow();w.resize(1920,1080);w.show()
for _ in range(5):app.processEvents()
ui=open("rg_studio_ui.py",encoding="utf-8").read()
ok=(w.tabs.count()>0 and 'setText("ЗАПУЩЕНО")' in ui and 'color:#ef4444' in ui and 'RG_PACK400_START_GUARD' in ui)
print("PACK400_UI_PROBE|"+json.dumps({"passed":ok,"tabs":w.tabs.count()},ensure_ascii=False))
raise SystemExit(0 if ok else 7)
""",encoding="utf-8")
        up=subprocess.run([smoke_py,"-X","utf8",str(probe)],cwd=str(dry),env=pe,
                          capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=100)
        if up.returncode!=0 or "PACK400_UI_PROBE|" not in (up.stdout or ""):
            raise RuntimeError("PACK400 UI probe failed: "+(up.stdout or "")[-10000:]+(up.stderr or "")[-10000:])

        files=[]
        for p in (inst,notes,matrix):
            files.append({"path":p.name,"sha256":_sha(p),"size":p.stat().st_size})
        manifest={
          "schema":"RG_UPDATE_MANIFEST_V2","product":"RG Auto Edit Studio","studio_version":VERSION,
          "channel":"STABLE","summary":"PACK400 PRODUCTIVITY 1-50","created_at":"2026-10-06",
          "files":files,"coverage":{"from":1,"to":50,"count":50},
          "core_modified":True,"ui_only":False,"expected_ui_change":True,
          "base":"current live Studio at build time",
          "safety":{"installed_during_build":False,"dry_run_on_live_copy":True,"compile_gate":True,
                    "import_smoke":True,"ui_probe":True,"feature_matrix_gate":True,
                    "rollback":True,"original_source_direct_locked":True,
                    "audio_processing_policy_unchanged":True}
        }
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
            if hashlib.sha256(b).hexdigest()!=row["sha256"] or len(b)!=row["size"]:
                raise RuntimeError("manifest mismatch "+row["path"])
        matrix=json.loads(zz.read("PACK400_FEATURE_MATRIX.json").decode("utf-8"))
        if int((matrix.get("coverage") or {}).get("count") or 0)!=50:
            raise RuntimeError("feature matrix count != 50")

    return {
      "status":"READY","version":VERSION,"pack":PACK,"coverage":"1-50",
      "zip":str(zip_path),"nas_copy":str(nas_copy),"size":zip_path.stat().st_size,"sha256":_sha(zip_path),
      "installed":False,"active_stream_touched":False,
      "dry_run_current_live_copy":"PASS","compile":"PASS","import_smoke":"PASS","ui_probe":"PASS",
      "selftest":"READY FOR PRODUCTION","feature_matrix":"50/50","crc":"PASS","manifest":"PASS"
    }
