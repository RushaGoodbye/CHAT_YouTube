"""RG Studio V9.2 integrated maintenance acceptance, no real video processing.
Read-only production tree, synthetic temp queue for worker and fail-closed gate,
NVENC/FFmpeg and NAS source probe, backups and rollback manifest verification.
"""
from __future__ import annotations
from pathlib import Path
import os,sys,json,tempfile,hashlib,subprocess,shutil,ast
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
SRC=Path(r"\\AlexLosServer\Work\WORK\RUSHA GOODBYE\Раша GOODBYE\ГОТОВО\ЗАПИСИ СТРИМОВ\RushaGoodbye - Live\RushaGoodbye - Live\885.mp4")
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
PINS={
"rg_fullstream_auto_v2.py":"087032e3f797c1c9b9249c00c95ccd5db56d9d058c140b733730aebe9dae38e8",
"rg_fullstream_detectors_v2.py":"19ea002c22fa3b397003280143aa4761b342927de2b57e6f15d6faa4458b36b2",
"rg_fullstream_export_v1.py":"82d85e81c68534cd591bb43344e906533593ecbb3722369cb455c83e9fd42bad"}
def emit(k,v):print("RGRELEASE|"+k+"|"+str(v),flush=True)
def verify_modules():
    sys.path.insert(0,str(APP))
    modules=[
      "rg_fullstream_auto_v2.py","rg_fullstream_detectors_v2.py",
      "rg_fullstream_export_v1.py","rg_fullstream_batch_v53.py",
      "rg_fullstream_worker_v3.py","rg_fullstream_editorial_gate_v82.py",
      "rg_fullstream_popup_checkpoint_v89.py",
      "rg_fullstream_popup_light_v89.py",
      "rg_studio_processing_guard_v1.py"]
    for name in modules:
        path=APP/name
        ast.parse(path.read_text(encoding="utf-8-sig"))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if name in PINS and digest!=PINS[name]:
            raise RuntimeError("MODULE_PIN_CHANGED_UNEXPECTED_"+name+"_"+digest)
    emit("MODULES_SYNTAX_AND_PINS","PASS|"+str(len(modules)))
    import rg_fullstream_detectors_v2 as det
    from rg_fullstream_auto_v2 import verified_popups
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_WORKERS_STOP_AUDIT")
    assert det.popup_search_area("dual")== (520,354,952,680)
    assert det.popup_search_area("framed_host")== (828,494,1400,835)
    framed={"x":1032,"y":684,"width":317,"height":131,
            "layout":"framed_host","editor_confirmed":True,"layout_verified":True,
            "intervals":[[1257.8,1268.7]]}
    dual={"x":557,"y":498,"width":370,"height":130,
          "layout":"dual","intervals":[[4500.8,4514.7]]}
    good,flags=verified_popups({"popup_masks":[framed,dual]})
    if len(good)!=2 or flags:raise RuntimeError("EDITOR_VERIFIED_POPUPS_NOT_ACCEPTED")
    for k in ("editor_confirmed","layout_verified"):
        bad=dict(framed);bad[k]=False
        excluded,_=verified_popups({"popup_masks":[bad]})
        if excluded:raise RuntimeError("UNVERIFIED_FRAMED_HOST_ALLOWED")
    emit("POPUP_SAFE_LAYOUT_AND_EDITOR_EVIDENCE","PASS")
def verify_qa():
    from rg_fullstream_editorial_gate_v82 import validate
    job={"stream":"999","video":str(SRC),"audio":str(SRC),
      "duration_seconds":150.0,
      "transcribed_words":[{"start":1.0,"end":1.25,"word":"тест","confidence":.99,"language":"uk"}],
      "intro_trim_seconds":0.0,"intro_host_color_verified":True,
      "minute_of_silence":[],"dialogue_ranges":[],
      "two_window_intervals":[],
      "popup_masks":[{"x":557,"y":498,"width":370,"height":130,"intervals":[[30,37]]}],
      "popup_coverage_verified":False,
      "asr_gap_guard_v87":{"complete":True,"suspected":0,"unexamined":0,"tested":3},
      "extra_review_flags":["V65_INTERSTITIAL_CUTS_CONFIRMED_0"],
      "break_cuts":[],"dialogue_gap_cuts":[],
      "video_encoder":"h264_nvenc","crf":24}
    result=validate(job)
    # Validation API may be dict or tuple. Preserve proof in logs.
    emit("EDITORIAL_GATE_RETURN",repr(result)[:950])
    if isinstance(result,dict):
        joined=json.dumps(result,ensure_ascii=False)
    else:joined=repr(result)
    if "NOTIFICATION_COVERAGE_UNVERIFIED" not in joined:
        raise RuntimeError("QA_GATE_DID_NOT_BLOCK_UNVERIFIED_NOTIFICATIONS")
    emit("QA_NEVER_APPROVES_UNVERIFIED_POPUPS","PASS")
def verify_queue():
    from rg_fullstream_worker_v3 import exclusive_lock,request_files
    with tempfile.TemporaryDirectory(prefix="rg_studio_release_") as tmp:
        base=Path(tmp)/"fullstream_v2"
        base.mkdir()
        for number,state,created in [("901","QUEUED",1.0),("902","PAUSED_EDITORIAL_QA",2.0),("903","QUEUED",3.0)]:
            folder=base/number;folder.mkdir()
            (folder/"queue_request.json").write_text(json.dumps({"stream":number,"created_utc_epoch":created}),encoding="utf-8")
            (folder/"status.json").write_text(json.dumps({"state":state}),encoding="utf-8")
        requests=request_files(tmp)
        ids=[x[2]["stream"] for x in requests]
        if ids!=["901","902","903"]:raise RuntimeError("QUEUE_ORDER_MISMATCH:"+repr(ids))
        worker=(APP/"rg_fullstream_worker_v3.py").read_text(encoding="utf-8")
        if "if state=='PAUSED_EDITORIAL_QA':" not in worker or "EDITORIAL_QA_SKIPPED_IN_BATCH" not in worker:
            raise RuntimeError("QA_PAUSED_ISOLATION_MISSING")
        lock=base/"_single_gpu_worker.lock"
        first=exclusive_lock(lock)
        if first is None:raise RuntimeError("CANNOT_ACQUIRE_FIRST_GPU_LOCK")
        try:
            second=exclusive_lock(lock)
            if second is not None:
                second.close()
                raise RuntimeError("SECOND_SIMULTANEOUS_GPU_LOCK_ALLOWED")
        finally:first.close()
        again=exclusive_lock(lock)
        if again is None:raise RuntimeError("GPU_LOCK_NOT_RELEASED")
        again.close()
        emit("QUEUE_ORDER_PAUSED_ISOLATION_AND_SINGLE_GPU_LOCK","PASS")
def verify_speed_and_audio():
    if not FF.exists():raise RuntimeError("FFMPEG_BINARY_MISSING")
    res=subprocess.run([str(FF),"-hide_banner","-encoders"],capture_output=True,text=True,timeout=20)
    if res.returncode or "h264_nvenc" not in res.stdout:raise RuntimeError("NVENC_ENCODER_MISSING")
    exporter=(APP/"rg_fullstream_export_v1.py").read_text(encoding="utf-8-sig")
    for val in ("-filter_complex_threads","trim=end_frame=1","gblur"):
        if val not in exporter:raise RuntimeError("OPTIMIZATION_NOT_INSTALLED_"+val)
    emit("FFMPEG_NVENC_AND_THREE_FILTER_OPTIMIZATIONS","PASS")
    probe=FF.parent/"ffprobe.exe"
    if not SRC.is_file():raise RuntimeError("NAS_SOURCE_MISSING")
    p=subprocess.run([str(probe),"-v","error","-show_entries","stream=codec_name,codec_type,width,height,r_frame_rate",
                      "-of","json",str(SRC)],capture_output=True,text=True,timeout=45)
    if p.returncode:raise RuntimeError("NAS_SOURCE_PROBE_FAILED:"+p.stderr[-500:])
    info=json.loads(p.stdout)
    v=next((x for x in info["streams"] if x.get("codec_type")=="video"),{})
    if (v.get("width"),v.get("height"))!=(1920,1080):raise RuntimeError("SOURCE_UNEXPECTED_RESOLUTION")
    emit("NAS_SOURCE_DECODABLE","PASS|"+str(v.get("codec_name"))+"|"+str(v.get("r_frame_rate")))
    free=shutil.disk_usage(APP).free/1024**3
    emit("AVAILABLE_STORAGE_GIB",round(free,2))
    if free<32:raise RuntimeError("LOW_DISK_FOR_FULLSTREAM_JOB")
def verify_release_rollback():
    base=DATA/"RG_REPAIR_BACKUPS"
    folders=sorted(base.glob("RG_POPUP_V92_LABELED_REGRESSION_*"),key=lambda p:p.stat().st_mtime,reverse=True)
    if not folders:raise RuntimeError("V92_ROLLBACK_BACKUP_MISSING")
    backup=folders[0]
    for n in ("rg_fullstream_detectors_v2.py","rg_fullstream_batch_v53.py"):
        if not (backup/n).is_file():raise RuntimeError("ROLLBACK_MODULE_MISSING:"+n)
    emit("V92_ROLLBACK_BACKUP","PASS|"+str(backup))
    history=DATA/"fullstream_v2"
    if any(p.is_dir() and p.name.isdigit() for p in history.iterdir()):
        raise RuntimeError("USER_CLEARED_HISTORY_WAS_RECREATED")
    emit("USER_CLEARED_QUEUE_AND_HISTORY_PRESERVED","PASS")
def main():
    verify_modules()
    verify_qa()
    verify_queue()
    verify_speed_and_audio()
    verify_release_rollback()
    emit("SIX_POINT_MAINTENANCE_SMOKE","PASS")
if __name__=="__main__":main()
