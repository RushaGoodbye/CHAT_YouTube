"""RG Auto Edit Studio direct-F launch and C cleanup.

Back up shortcuts and obsolete Program Files Studio EXE to F first.
Rewrite only the THREE known RG Auto Edit Studio shortcuts to call F runtime
with F rg_studio_main.py. Remove obsolete C:\\Program Files\\RG Auto Edit Studio
only after byte-for-byte F backup, no active Studio or video worker.
Keep all C NTFS junctions targeting F intact for existing legacy paths:
deleting junction contents would DESTROY F storage.
Do not touch global Python base, YouTube Control, Media Deck or caches.
"""
from pathlib import Path
import os,sys,json,shutil,hashlib,uuid,time,subprocess
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
RUNTIME=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
OLD=Path(r"C:\Program Files\RG Auto Edit Studio")
CBASE=Path(r"C:\Users\fauto\AppData\Local\Programs")
C_DATA=Path(r"C:\Users\fauto\AppData\Local\RG_Auto_Edit")
SHORTCUTS=[
 Path(r"C:\Users\fauto\Desktop\RG Auto Edit Studio.lnk"),
 Path(r"C:\Users\fauto\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\RG Auto Edit Studio.lnk"),
 Path(r"C:\Users\fauto\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\РАША ГУДБАЙ МОНТАЖКА.lnk")]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def is_junction(path,target):
    p=Path(path)
    if not p.is_junction():raise RuntimeError("NOT_JUNCTION_"+str(p))
    if p.resolve().as_posix().casefold()!=Path(target).resolve().as_posix().casefold():
        raise RuntimeError("JUNCTION_TARGET_MISMATCH_"+str(p))
def enumerate_folders(root):
    files={}
    for p in root.rglob("*"):
        if p.is_symlink() or p.is_junction():raise RuntimeError("OLD_INSTALL_CONTAINS_REPARSE_POINT")
        if p.is_file():files[str(p.relative_to(root))]=sha(p)
    return files
def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if not APP.is_dir() or not RUNTIME.is_dir() or not DATA.is_dir():
        raise RuntimeError("F_ROOT_MISSING")
    is_junction(CBASE/"RG Auto Edit",APP)
    is_junction(CBASE/"RG Auto Edit Runtime",RUNTIME)
    is_junction(C_DATA,DATA)
    mainpy=APP/"rg_studio_main.py"
    pyw=RUNTIME/"venv"/"Scripts"/"pythonw.exe"
    py=RUNTIME/"venv"/"Scripts"/"python.exe"
    if not mainpy.is_file() or not pyw.is_file() or not py.is_file():
        raise RuntimeError("DIRECT_F_START_MISSING")
    from subprocess import run
    code="import sys;print(sys.executable);print(sys.prefix);import PySide6;print('RG_F_PYSIDE6_OK')"
    result=run([str(py),"-X","utf8","-c",code],capture_output=True,text=True,timeout=25)
    if result.returncode or "RG_F_PYSIDE6_OK" not in result.stdout:
        raise RuntimeError("DIRECT_F_RUNTIME_TEST_FAILED:"+result.stderr[-500:])
    print("RGFMOVE|F_PYTHON_QT|PASS|"+result.stdout.strip().replace("\n","|"),flush=True)
    import psutil
    running=[]
    for p in psutil.process_iter(["pid","name","cmdline"]):
        try:
            name=(p.info["name"] or "").lower()
            cmd=" ".join(p.info["cmdline"] or []).lower()
            if ("rg_studio_main.py" in cmd or
                "rg_fullstream_worker_v3" in cmd or
                name=="rg auto edit studio.exe"):
                running.append({"pid":p.info["pid"],"name":name,"cmd":cmd[:130]})
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    if running:raise RuntimeError("STUDIO_OR_FULLSTREAM_ACTIVE_NO_CLEANUP:"+repr(running))
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("RG_WORKER_NOT_IDLE")
    # Explicitly scoped old *non-junction* installation only
    if not OLD.is_dir() or OLD.is_junction() or OLD.is_symlink():
        raise RuntimeError("OLD_C_PROGRAM_FILES_NOT_REAL_DIRECTORY")
    original_files=enumerate_folders(OLD)
    if not ("RG Auto Edit Studio.exe" in original_files and len(original_files)<=50):
        raise RuntimeError("OLD_INSTALL_UNEXPECTED_CONTENTS")
    if len(original_files)!=13:raise RuntimeError("OLD_INSTALL_CHANGED_FILE_COUNT")
    # Do not touch links that are backing the F canonical directories
    print("RGFMOVE|C_JUNCTIONS|3|KEPT_FOR_LEGACY_COMPAT",flush=True)
    for p in SHORTCUTS:
        if not p.is_file():raise RuntimeError("EXPECTED_STUDIO_SHORTCUT_MISSING_"+str(p))
    print("RGFMOVE|OLD_REAL_C_BYTES|"+str(sum(p.stat().st_size for p in OLD.rglob("*") if p.is_file())),flush=True)
    if not args.apply:
        print("RGFMOVE|DRYRUN|PASS|THREE_SHORTCUTS_AND_OLD_PROGRAM_FILES_ONLY",flush=True)
        return
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_F_ONLY_MIGRATION_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True,exist_ok=False)
    saved=backup/"old_C_ProgramFiles_RG_Auto_Edit_Studio"
    shutil.copytree(OLD,saved,symlinks=True)
    if enumerate_folders(saved)!=original_files:
        raise RuntimeError("OLD_C_BACKUP_SHA256_MISMATCH")
    # Back up every .lnk as raw file for exact rollback
    for i,sc in enumerate(SHORTCUTS):
        (backup/f"shortcut_{i}_before.lnk").write_bytes(sc.read_bytes())
    (backup/"migration_manifest.json").write_text(json.dumps({
        "source_C_program_files":str(OLD),
        "backup_old_executable":str(saved),
        "canonical_app":str(APP),"canonical_runtime":str(RUNTIME),
        "canonical_data":str(DATA),
        "shortcuts":[str(s) for s in SHORTCUTS],
        "old_exe_files_sha256":original_files,
        "c_junctions_retained":True,
        "shared_c_python_not_removed":True,
        "undo":"Restore old shortcut backups; only restore old exe if necessary.",
    },ensure_ascii=False,indent=2),encoding="utf-8")
    # .lnk via native Windows COM. No browser/remote shell.
    import win32com.client
    shell=win32com.client.Dispatch("WScript.Shell")
    changed=[]
    try:
        for i,sc in enumerate(SHORTCUTS):
            link=shell.CreateShortcut(str(sc))
            link.TargetPath=str(pyw)
            link.Arguments=f'-X utf8 "{mainpy}"'
            link.WorkingDirectory=str(APP)
            link.Description="RG Auto Edit Studio — запуск з диска F:"
            link.Save()
            changed.append(i)
        for sc in SHORTCUTS:
            link=shell.CreateShortcut(str(sc))
            if (Path(link.TargetPath).resolve()!=pyw.resolve() or
                str(mainpy).lower() not in link.Arguments.lower() or
                Path(link.WorkingDirectory).resolve()!=APP.resolve()):
                raise RuntimeError("NEW_STUDIO_SHORTCUT_VERIFICATION_FAILED_"+str(sc))
        if running or active_workers() or worker_lock_state(DATA)!="IDLE":
            raise RuntimeError("WORKER_STARTED_DURING_MIGRATION")
        # First remove ONLY known and fully backed-up obsolete 17MB C installation.
        shutil.rmtree(OLD)
        if OLD.exists():raise RuntimeError("OLD_INSTALL_REMAINS")
        print("RGFMOVE|OLD_C_EXE_REMOVED|PASS|BACKUP|"+str(saved),flush=True)
    except BaseException:
        for i in changed:
            try:SHORTCUTS[i].write_bytes((backup/f"shortcut_{i}_before.lnk").read_bytes())
            except Exception:pass
        # Old program is restored if deleted and F backup verified.
        if not OLD.exists():
            try:shutil.copytree(saved,OLD)
            except Exception:pass
        print("RGFMOVE|ROLLBACK|ATTEMPTED|"+str(backup),flush=True)
        raise
    print("RGFMOVE|DIRECT_F_SHORTCUTS|3|PASS",flush=True)
    for p in SHORTCUTS:print("RGFMOVE|F_SHORTCUT|"+str(p),flush=True)
    print("RGFMOVE|C_OLD_EXE_SIZE_REMOVED|"+str(sum(p.stat().st_size for p in saved.rglob("*") if p.is_file())),flush=True)
    print("RGFMOVE|C_DATA_JUNCTIONS_UNTOUCHED|PASS",flush=True)
    print("RGFMOVE|F_BACKUP|"+str(backup),flush=True)
    print("RGFMOVE|NO_VIDEO_OR_STUDIO_LAUNCH|PASS",flush=True)
if __name__=="__main__":main()
