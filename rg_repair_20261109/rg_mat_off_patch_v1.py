"""RG Full Stream: remove ONLY profanity censorship from full-stream render + QA.
Staging is always isolated. Apply is transactional and forbidden while Studio/worker is live.
"""
import argparse, ast, hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
INSTALLED=Path(os.environ.get("LOCALAPPDATA",r"C:\Users\fauto\AppData\Local"))/"Programs"/"RG Auto Edit"
BACKUP=DATA/"RG_REPAIR_BACKUPS"
MODS=("rg_fullstream_export_v1.py","rg_fullstream_editorial_gate_v82.py","rg_fullstream_qa_v65.py")
BATCH="rg_fullstream_batch_v53.py"
VERSION="RG_FULLSTREAM_NO_PROFANITY_V1_20261109"

def sha(b):return hashlib.sha256(b).hexdigest()
def replace_one(s,old,new,label):
    count=s.count(old)
    if count!=1:raise RuntimeError(f"ANCHOR_MISMATCH:{label}:{count}")
    return s.replace(old,new,1)

def patch_export(s):
    s=replace_one(s,
        """    from rg_fullstream_quality_v3 import classify_words_v3
    auto_mute,review=classify_words_v3(words)""",
        """    # RG_NO_PROFANITY_V1: full-stream audio is never muted for language.
    # Other video/audio edits (cuts, popups, protected minute) are unchanged.
    auto_mute,review=[],[]""","EXPORT_MAT_CLASSIFY")
    s=replace_one(s,
        """    extra=valid_rescue_mutes_v88(job.get('rescue_mute_evidence_v88'),audio,duration)
    muted=merge_intervals([(max(0,a),min(duration,b)) for a,b in auto_mute]+extra)""",
        """    extra=[]
    muted=[]  # RG_NO_PROFANITY_V1: no automatic or rescue profanity muting""","EXPORT_RESCUE_MUTES")
    s=replace_one(s,
        "    flags.append('V70_CENSOR_ONLY_MAT_WORDS_NO_INSULTS')",
        "    flags.append('RG_FULLSTREAM_MAT_CENSORSHIP_DISABLED_BY_USER')","EXPORT_FLAG")
    s=replace_one(s,
        "    if not job.get('transcript_double_checked',False):flags.append('PROFANITY_NOT_DOUBLE_CHECKED')",
        "    # Full-stream profanity proofreading is no longer a render requirement.","EXPORT_DOUBLE_CHECK")
    s=replace_one(s,
        "    if not desc['censorship_applied']:\n        desc['review_flags'].append('CRITICAL_NO_AUDIO_CENSORING_APPLIED')",
        "    # No profanity mute is intended; zero muted spans is correct.\n    desc['censorship_policy']='DISABLED_BY_USER_FULL_STREAM_ONLY'","EXPORT_POST_QA")
    return s

def patch_gate(s):
    s=replace_one(s,
        """    if not job.get("transcript_double_checked",False):
        warnings.append("PROFANITY_COVERAGE_UNVERIFIED")""",
        """    # RG_NO_PROFANITY_V1: language is intentionally not censored in full streams.""","GATE_DOUBLE_CHECK")
    s=replace_one(s,
        """            elif int(v90.get('pending_count') or 0)>0:
                failures.append("V90_UNRESOLVED_ONE_SIDED_PROFANITY_"+str(v90['pending_count']))""",
        """            elif int(v90.get('pending_count') or 0)>0:
                warnings.append("V90_PROFANITY_REVIEW_DISABLED_BY_USER")""","GATE_ONE_SIDED")
    s=replace_one(s,
        """    if token_audit["pending_review_count"]:
        failures.append("KNOWN_MAT_MATCHES_NOT_MUTED_OR_REVIEWED_"+str(token_audit["pending_review_count"]))""",
        """    # RG_NO_PROFANITY_V1: recognized MAT words are allowed without muting.""","GATE_TOKEN")
    s=replace_one(s,
        '        "PROFANITY_COVERAGE_UNVERIFIED",\n',
        '',"GATE_MUST_PROVE")
    return s

def patch_qa(s):
    s=replace_one(s,
       "REQUIRED={'censorship','notifications','silence','minute','underlay'}",
       "REQUIRED={'notifications','silence','minute','underlay'}","QA_REQUIRED")
    s=replace_one(s,
       """        'censorship': ('PLANNED_EDIT_UNVERIFIED_COVERAGE' if mute_count>0 and word_count>0 else
                       'NOT_PROVEN_NO_MUTED_INTERVALS_OR_ASR'),""",
       """        'censorship': 'DISABLED_BY_USER_FULL_STREAM_ONLY',""","QA_CENSOR_STATUS")
    return s

PATCH={"rg_fullstream_export_v1.py":patch_export,
       "rg_fullstream_editorial_gate_v82.py":patch_gate,
       "rg_fullstream_qa_v65.py":patch_qa}

def stage():
    before={n:(APP/n).read_bytes() for n in (*MODS,BATCH)}
    after={}
    for n in MODS:
        s=before[n].decode("utf-8-sig")
        a=PATCH[n](s)
        ast.parse(a,filename=n)
        after[n]=a.encode("utf-8")
    batch=before[BATCH].decode("utf-8-sig")
    for n in MODS:
        old=sha(before[n]);new=sha(after[n])
        # Hash table may not contain QA helper, but if present update it.
        if old in batch:
            if batch.count(old)!=1:raise RuntimeError("DUPLICATE_BATCH_HASH:"+n)
            batch=batch.replace(old,new,1)
        elif n in batch and n!="rg_fullstream_qa_v65.py":
            raise RuntimeError("BATCH_INTEGRITY_HASH_MISSING:"+n)
    ast.parse(batch,filename=BATCH)
    after[BATCH]=batch.encode("utf-8")
    for n in (*MODS,BATCH):
        assert sha((APP/n).read_bytes())==sha(before[n]),"SOURCE_CHANGED_DURING_STAGE:"+n
    return before,after

def safety():
    ps=r'''Get-CimInstance Win32_Process | Where-Object {
 $_.Name -match '^(python|pythonw|ffmpeg)(\.exe)?$|RG.Auto.Edit' -and
 $_.CommandLine -match 'rg_studio_main\.py|rg_studio_ui\.py|rg_fullstream_auto_v2\.py|rg_fullstream_worker_v3\.py|rg_production_wrapper\.py|rg_multi_dialogue\.py'
}|Select-Object ProcessId,Name,CommandLine|ConvertTo-Json -Compress'''
    r=subprocess.run(["powershell.exe","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=25,encoding="utf-8",errors="replace")
    if r.returncode!=0:raise RuntimeError("PROCESS_CHECK_FAILED")
    procs=json.loads(r.stdout) if r.stdout.strip() else []
    procs=procs if isinstance(procs,list) else [procs]
    if procs:raise RuntimeError("ACTIVE_STUDIO_OR_VIDEO_WORKER:"+",".join(str(x["ProcessId"]) for x in procs))
    for folder in (DATA/"fullstream_v2",):
        for lock in folder.glob("*/*lock*"):
            if lock.is_file() and lock.name.lower() in ("worker.lock","process.lock"):
                raise RuntimeError("WORKER_LOCK_PRESENT:"+str(lock))

def test(before,after):
    ex=after["rg_fullstream_export_v1.py"].decode()
    gate=after["rg_fullstream_editorial_gate_v82.py"].decode()
    qa=after["rg_fullstream_qa_v65.py"].decode()
    assert "auto_mute,review=[],[]" in ex and "    muted=[]  # RG_NO_PROFANITY_V1" in ex
    assert "V90_UNRESOLVED_ONE_SIDED_PROFANITY_"+"" not in gate
    assert 'failures.append("KNOWN_MAT_MATCHES_NOT_MUTED_OR_REVIEWED_"' not in gate
    assert '"NOTIFICATION_COVERAGE_UNVERIFIED"' in gate
    assert "NOTIFICATION_SCAN_NOT_CONFIRMED" in gate
    assert "POPUP_COVERAGE_NOT_VERIFIED" in ex
    assert "REQUIRED={'notifications','silence','minute','underlay'}" in qa
    assert "'censorship': 'DISABLED_BY_USER_FULL_STREAM_ONLY'" in qa
    assert "'-cq',str(job.get('crf',20))" in ex
    print("RGMATOFF|STATIC_REGRESSION|PASS",flush=True)

def apply(before,after):
    safety()
    targets=[]
    for root in (APP,INSTALLED):
        for name in (*MODS,BATCH):
            p=root/name
            if p.is_file():
                if root!=APP and p.read_bytes()!=before[name]:
                    raise RuntimeError("INSTALLED_SOURCE_DIVERGED:"+str(p))
                targets.append((p,name))
            elif root==APP:
                raise RuntimeError("APP_SOURCE_MISSING:"+name)
    folder=BACKUP/(VERSION+"_"+time.strftime("%Y%m%d_%H%M%S"))
    folder.mkdir(parents=True,exist_ok=False)
    ledger=[]
    for i,(p,n) in enumerate(targets):
        backup=folder/("original_"+str(i)+"_"+n)
        shutil.copy2(p,backup)
        if sha(p.read_bytes())!=sha(backup.read_bytes()):raise RuntimeError("BACKUP_FAILED")
        ledger.append({"original":str(p),"backup":str(backup),"old_sha256":sha(backup.read_bytes()),"new_sha256":sha(after[n])})
    (folder/"ROLLBACK_LEDGER.json").write_text(json.dumps({"version":VERSION,"entries":ledger,"status":"BACKUP_READY"},indent=2),encoding="utf-8")
    safety()
    done=[]
    try:
        for p,n in targets:
            if p.read_bytes()!=before[n]:raise RuntimeError("SOURCE_RACED:"+str(p))
            tmp=p.with_name(p.name+".rgmatofftmp")
            tmp.write_bytes(after[n])
            if sha(tmp.read_bytes())!=sha(after[n]):raise RuntimeError("CANDIDATE_COPY_FAILED")
            os.replace(tmp,p)
            done.append(p)
        for p,n in targets:
            if sha(p.read_bytes())!=sha(after[n]):raise RuntimeError("VERIFY_FAILED:"+str(p))
    except Exception:
        for p in reversed(done):
            backup=next(Path(x["backup"]) for x in ledger if x["original"]==str(p))
            shutil.copy2(backup,p)
        raise
    (folder/"ROLLBACK_LEDGER.json").write_text(json.dumps({"version":VERSION,"entries":ledger,"status":"INSTALLED"},indent=2),encoding="utf-8")
    return folder

def main():
    args=argparse.ArgumentParser()
    args.add_argument("--apply",action="store_true")
    opt=args.parse_args()
    before,after=stage()
    test(before,after)
    print("RGMATOFF|STAGE|PASS|"+",".join(MODS+(BATCH,)),flush=True)
    if opt.apply:
        folder=apply(before,after)
        print("RGMATOFF|INSTALL|PASS|BACKUP="+str(folder),flush=True)
    else:
        print("RGMATOFF|INSTALL|NOT_ATTEMPTED",flush=True)
if __name__=="__main__":main()
