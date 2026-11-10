"""Archive stable Full Stream Python core as immutable verified rollback snapshot.
Not a full installer; excludes user dialogue media, inputs, videos and all secrets.
Archive + manifest stored on F: alongside existing before-change backups.
"""
from pathlib import Path
import hashlib,zipfile,json,time,uuid,sys,os,tempfile
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
DEST=DATA/"RG_REPAIR_BACKUPS"
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("WORKER_ACTIVE_DURING_RELEASE_BACKUP")
    files=sorted(APP.glob("rg_fullstream_*.py"))
    extras=["rg_studio_processing_guard_v1.py","rg_studio_single_instance_v1.py"]
    files.extend(APP/n for n in extras if (APP/n).is_file())
    files=list(dict.fromkeys(files))
    if len(files)<25:raise RuntimeError("CORE_MODULES_TOO_FEW:"+str(len(files)))
    expected={"rg_fullstream_detectors_v2.py":"19ea002c22fa3b397003280143aa4761b342927de2b57e6f15d6faa4458b36b2",
              "rg_fullstream_auto_v2.py":"087032e3f797c1c9b9249c00c95ccd5db56d9d058c140b733730aebe9dae38e8",
              "rg_fullstream_export_v1.py":"82d85e81c68534cd591bb43344e906533593ecbb3722369cb455c83e9fd42bad"}
    for n,digest in expected.items():
        if sha(APP/n)!=digest:raise RuntimeError("PRODUCTION_CHANGED_"+n)
    name="RG_STABLE_FULLSTREAM_V92_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5]
    folder=DEST/name
    folder.mkdir(parents=True,exist_ok=False)
    archive=folder/"RG_FULLSTREAM_V92_CODE_SNAPSHOT.zip"
    manifest={
      "version":"RG_STABLE_FULLSTREAM_V92",
      "scope":"Full Stream Python modules and Studio processing guard only; not a full application installer",
      "source":str(APP),"created_local":time.strftime("%Y-%m-%d %H:%M:%S"),
      "no_video_or_source_media":True,
      "no_queue_or_history":True,
      "studio_required_for_real_processing":True,
      "files":{p.name:{"sha256":sha(p),"size_bytes":p.stat().st_size} for p in files},
      "restore_only_when_worker_idle":True,
      "prior_patches_backups":[
        "RG_RENDER_FAST_V3_20261110_133025_475887",
        "RG_EDITOR_FRAMED_HOST_V1_20261110_171302_6b2bc"]
    }
    import ast
    for p in files:ast.parse(p.read_text(encoding="utf-8-sig"))
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,arcname=p.name)
        z.writestr("MANIFEST.json",json.dumps(manifest,ensure_ascii=False,indent=2))
    (folder/"MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    with zipfile.ZipFile(archive,"r") as z:
        if z.testzip() is not None:raise RuntimeError("ZIP_CRC_FAILED")
        for name,v in manifest["files"].items():
            if hashlib.sha256(z.read(name)).hexdigest()!=v["sha256"]:
                raise RuntimeError("ZIP_SHA256_FAILURE_"+name)
    if active_workers():raise RuntimeError("WORKER_STARTED_SNAPSHOT_COMPLETED_WITHOUT_CODE_WRITE")
    print("RGSTABLE|VERSION|V92",flush=True)
    print("RGSTABLE|MODULES|"+str(len(files)),flush=True)
    print("RGSTABLE|SNAPSHOT|"+str(archive),flush=True)
    print("RGSTABLE|BYTES|"+str(archive.stat().st_size),flush=True)
    print("RGSTABLE|ZIP_INTEGRITY_SHA256|"+hashlib.sha256(archive.read_bytes()).hexdigest(),flush=True)
    print("RGSTABLE|MANIFEST|"+str(folder/"MANIFEST.json"),flush=True)
    print("RGSTABLE|NO_MEDIA_OR_QUEUE_TOUCHED|PASS",flush=True)
    print("RGSTABLE|RELEASE_CORE_SNAPSHOT_VERIFIED|PASS",flush=True)
if __name__=="__main__":main()
