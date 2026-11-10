"""RG V9.3 install actionable popup editorial QA in Studio.

Enrich the existing fail-closed block with exact rejected notification
timecodes and unknown-layout counts. Never auto-approve or start rendering.
Backs up engine files and updates expected SHA pins atomically when worker IDLE.
"""
from __future__ import annotations
from pathlib import Path
import os,sys,hashlib,ast,time,uuid,shutil,argparse,json,importlib.util
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
NAMES=("rg_fullstream_auto_v2.py","rg_fullstream_editorial_gate_v82.py","rg_fullstream_batch_v53.py")
HELPER="rg_fullstream_qa_actionable_v93.py"
AUTO_OLD="    gate=validate(job,metadata)"
AUTO_NEW="""    # V9.3: attach source-bound exact rejected-card times to the fail-closed QA
    # report, without reopening source video or granting export permission.
    from rg_fullstream_qa_actionable_v93 import evidence_for_job
    job['notification_qa_v93']=evidence_for_job(
        Path(data)/'fullstream_v2'/str(stream),job)
    gate=validate(job,metadata)"""
GATE_OLD="""    if "NOTIFICATION_COVERAGE_UNVERIFIED" in failures:
        review_queue.append({"kind":"POPUP_VISUAL_COVERAGE",
            "status":"SOURCE_WIDE_SCAN_AND_EDITORIAL_QA_REQUIRED",
            "auto_approve":False})"""
GATE_NEW="""    if "NOTIFICATION_COVERAGE_UNVERIFIED" in failures:
        record={"kind":"POPUP_VISUAL_COVERAGE",
            "status":"SOURCE_WIDE_SCAN_AND_EDITORIAL_QA_REQUIRED",
            "auto_approve":False}
        case=job.get("notification_qa_v93")
        if isinstance(case,dict) and case.get("schema")=="RG_SOURCE_BOUND_POPUP_REVIEW_V93":
            # Counts of scanned frames are NOT proof of absence of popups.
            record["source_scan_sampled_frames"]=int(case.get("source_scan_sampled_frames") or 0)
            record["unknown_layout_samples"]=int(case.get("unknown_layout_samples") or 0)
            record["rejected_candidate_count"]=int(case.get("rejected_candidate_count") or 0)
            record["review_images"]=case.get("review_images") or {}
            record["coverage_automatically_certified"]=False
        review_queue.append(record)
        if isinstance(case,dict):
            for item in (case.get("rejected_candidates") or [])[:40]:
                review_queue.append({
                    "kind":"POPUP_VISUAL_REJECTED_CANDIDATE",
                    "candidate_index":int(item["candidate_index"]),
                    "source_start_seconds":float(item["source_start_seconds"]),
                    "source_end_seconds":float(item["source_end_seconds"]),
                    "status":"HUMAN_VISUAL_CONFIRMATION_REQUIRED",
                    "auto_approve":False})"""
def sha(b):return hashlib.sha256(b).hexdigest()
def encode(old,code):
    ast.parse(code)
    bom=old.startswith(b"\xef\xbb\xbf")
    e=code.replace("\r\n","\n").encode("utf-8")
    if b"\r\n" in old:e=e.replace(b"\n",b"\r\n")
    return (b"\xef\xbb\xbf" if bom else b"")+e
def prepare():
    files={n:(APP/n).read_bytes() for n in NAMES}
    scripts={
        NAMES[0]:(AUTO_OLD,AUTO_NEW),
        NAMES[1]:(GATE_OLD,GATE_NEW)}
    new={}
    for name,(before,after) in scripts.items():
        txt=files[name].decode("utf-8-sig")
        if txt.count(before)!=1:raise RuntimeError("V93_PATCH_ANCHOR_CHANGED_"+name)
        txt=txt.replace(before,after,1)
        new[name]=encode(files[name],txt)
    batch=files[NAMES[2]]
    tx=batch.decode("utf-8-sig")
    pins=0
    for name in (NAMES[0],NAMES[1]):
        originalsha,newsha=sha(files[name]),sha(new[name])
        count=tx.count(originalsha)
        if count>1:raise RuntimeError("AMBIGUOUS_V93_ENGINE_HASH_PIN_"+name)
        if name==NAMES[0] and count!=1:raise RuntimeError("AUTO_ENGINE_PIN_MISSING")
        if count:
            tx=tx.replace(originalsha,newsha,1)
            pins+=1
    new[NAMES[2]]=encode(batch,tx)
    helper=(Path(__file__).parent/HELPER).read_bytes()
    if (APP/HELPER).exists():raise RuntimeError("V93_HELPER_ALREADY_EXISTS")
    ast.parse(helper.decode("utf-8-sig"))
    new[HELPER]=helper
    print("RGV93PATCH|ENGINE_HASH_PINS_UPDATED|"+str(pins),flush=True)
    return files,new
def static_tests(new):
    from types import ModuleType
    sys.path.insert(0,str(APP))
    # Imports of the helper and patched editorial gate are isolated in memory.
    helper=ModuleType("rg_fullstream_qa_actionable_v93")
    exec(compile(new[HELPER].decode("utf-8-sig"),"<V93-helper>","exec"),helper.__dict__)
    root=DATA/"fullstream_v2"/"895"
    job=json.loads((root/"processing_plan.json").read_text(encoding="utf-8-sig"))
    case=helper.evidence_for_job(root,job)
    if (case["unknown_layout_samples"],case["source_scan_sampled_frames"],
        case["rejected_candidate_count"],case["accepted_automated_masks"])!=(1263,23188,3,20):
        raise RuntimeError("REAL_895_V93_EVIDENCE_COUNTS_CHANGED:"+repr(case))
    if [c["candidate_index"] for c in case["rejected_candidates"]] != [12,18,19]:
        raise RuntimeError("REAL_895_REJECTED_CANDIDATE_INDEX_CHANGED")
    if case["popup_coverage_verified"] or case["auto_approve"]:raise RuntimeError("FALSE_COVERAGE_AUTO_APPROVAL")
    mod=ModuleType("rg_fullstream_editorial_gate_v82_v93_test")
    exec(compile(new[NAMES[1]].decode("utf-8-sig"),"<V93-gate>","exec"),mod.__dict__)
    report=mod.validate(dict(job,notification_qa_v93=case),{"output":job.get("output","")})
    if report.get("decision")!="BLOCK" or report.get("publish_ready") is not False:
        raise RuntimeError("V93_GATE_BYPASS_OR_FALSE_PUBLISH")
    if report["blocking_reasons"]!=["NOTIFICATION_COVERAGE_UNVERIFIED"]:
        raise RuntimeError("V93_GATE_CHANGED_BLOCK_REASONS:"+repr(report["blocking_reasons"]))
    queue=report["review_queue"]
    if len(queue)!=4 or queue[0].get("unknown_layout_samples")!=1263:
        raise RuntimeError("V93_ACTIONABLE_QA_ITEMS_MISSING")
    if [x.get("candidate_index") for x in queue[1:]]!=[12,18,19]:
        raise RuntimeError("V93_QA_TIMES_INCORRECT")
    if any(x.get("auto_approve") for x in queue):raise RuntimeError("V93_AUTO_APPROVAL")
    emit=print
    print("RGV93PATCH|REAL_895_REJECTION_TIMECODES|12,18,19|PASS",flush=True)
    print("RGV93PATCH|UNKNOWN_LAYOUT_SAMPLES|1263/23188|PASS",flush=True)
    print("RGV93PATCH|EDITORIAL_QA_FAIL_CLOSED|BLOCK|PUBLISH_FALSE|PASS",flush=True)
    print("RGV93PATCH|QA_REVIEW_QUEUE_ITEMS|4|PASS",flush=True)
def install():
    files,new=prepare()
    static_tests(new)
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("V93_ACTIVE_WORKER_SAFE_STOP")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_NOTIFICATION_QA_V93_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True,exist_ok=False)
    for n,b in files.items():
        (backup/n).write_bytes(b)
        if (backup/n).read_bytes()!=b:raise RuntimeError("BACKUP_SHA_MISMATCH")
    applied=[]
    try:
        if active_workers() or worker_lock_state(DATA)!="IDLE":
            raise RuntimeError("WORKER_STARTED_AFTER_BACKUP")
        for n in (*NAMES,HELPER):
            p=APP/n
            if n in files and p.read_bytes()!=files[n]:raise RuntimeError("CONCURRENT_SOURCE_CHANGE")
            if n==HELPER and p.exists():raise RuntimeError("CONCURRENT_HELPER_CREATED")
            tmp=p.with_name(p.name+".v93.tmp")
            tmp.write_bytes(new[n])
            if tmp.read_bytes()!=new[n]:raise RuntimeError("V93_STAGING_HASH_FAIL")
            os.replace(tmp,p)
            applied.append(n)
        if any((APP/n).read_bytes()!=new[n] for n in (*NAMES,HELPER)):
            raise RuntimeError("V93_INSTALL_VERIFY_FAILED")
        print("RGV93PATCH|INSTALLED|PASS|BACKUP|"+str(backup),flush=True)
        print("RGV93PATCH|PRODUCTION_MEDIA_AND_QUEUE_UNTOUCHED|PASS",flush=True)
    except:
        for n in reversed(applied):
            if n in files:(APP/n).write_bytes(files[n])
            else:(APP/n).unlink(missing_ok=True)
        print("RGV93PATCH|ROLLBACK|ATTEMPTED",flush=True)
        raise
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--install",action="store_true")
    args=parser.parse_args()
    old,new=prepare()
    static_tests(new)
    if args.install:install()
if __name__=="__main__":main()
