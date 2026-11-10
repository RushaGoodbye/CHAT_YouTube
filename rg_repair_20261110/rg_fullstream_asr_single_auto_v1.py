"""RG ASR single adaptive-language pass with profanity-only V90 suppression.
Transactional install while Full Stream workers are idle. Does not spawn worker.
"""
import ast,hashlib,json,os,sys,time,uuid,argparse
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
CHUNK="rg_fullstream_asr_chunked_v58.py"
CHILD="rg_fullstream_asr_child_v58.py"
AUTO="rg_fullstream_auto_v2.py"
GATE="rg_fullstream_editorial_gate_v82.py"
BATCH="rg_fullstream_batch_v53.py"
FILES=[CHUNK,CHILD,AUTO,GATE,BATCH]
def output(*v):print("RGASRSINGLE|"+"|".join(str(x) for x in v),flush=True)
def sha(b):return hashlib.sha256(b).hexdigest()
def edit(s,old,new,what):
    if s.count(old)!=1:raise RuntimeError("ANCHOR_MISMATCH_"+what+"_"+str(s.count(old)))
    return s.replace(old,new,1)
def build(original):
    src={n:original[n].decode("utf-8-sig").replace("\r\n","\n") for n in FILES}
    s=src[CHUNK]
    s=edit(s,"LANGS=('ru','uk')","LANGS=('auto',)  # RG_ASR_SINGLE_AUTO_V1: one adaptive language pass per chunk","langs")
    s=edit(s,"counts={'ru':0,'uk':0}","counts={'auto':0}", "counts")
    s=edit(s,"f'ASR_PASS_RU_WORDS_{counts[\"ru\"]}',f'ASR_PASS_UK_WORDS_{counts[\"uk\"]}'",
           "f'ASR_PASS_AUTO_WORDS_{counts[\"auto\"]}'","resume_flags")
    # second flags use whitespace-indented expression and same shared anchor
    s=edit(s,"f'ASR_PASS_RU_WORDS_{counts[\"ru\"]}',f'ASR_PASS_UK_WORDS_{counts[\"uk\"]}'",
           "f'ASR_PASS_AUTO_WORDS_{counts[\"auto\"]}'","finish_flags")
    s=edit(s,"'ASR_UK' if 'UK ' in current else 'ASR_RU'","'ASR_AUTO'","ui_stage")
    # enforce the child receiving the same mode as the supervisor
    s=edit(s,"'--duration',str(duration),'--parent-pid'",
           "'--langs','auto','--duration',str(duration),'--parent-pid'","child_lang_argument")
    src[CHUNK]=s
    s=src[CHILD]
    s=edit(s,"for lang in ('ru','uk'):","for lang in ('auto',):  # RG_ASR_SINGLE_AUTO_V1","child_loop")
    s=edit(s,"segments,_=model.transcribe(str(wav),language=lang,beam_size=3,",
           "segments,_=model.transcribe(str(wav),language=None,beam_size=3,","faster_auto_language")
    s=edit(s,"result=model.transcribe(str(wav),language=lang,word_timestamps=True,verbose=False,fp16=True)",
           "result=model.transcribe(str(wav),language=None,word_timestamps=True,verbose=False,fp16=True)",
           "openai_auto_language")
    s=edit(s,"'--models',required=True)","'--models',required=True)","noop") if False else s
    s=edit(s,"ap.add_argument('--models',required=True);ap.add_argument('--duration',type=float,required=True)",
           "ap.add_argument('--models',required=True);ap.add_argument('--langs',default='auto',choices=['auto']);ap.add_argument('--duration',type=float,required=True)",
           "child_cli")
    src[CHILD]=s
    s=src[AUTO]
    old="""    # V9.0: every Silero speech window is independently re-transcribed
    # RU + UK with source-tied checkpoints. Only executed inside Studio or
    # an explicitly invoked technical QA test, never as a background daemon.
    from rg_fullstream_gap_followup_v90 import run as inspect_asr_gaps_v90
    stage('ASR_GAP_RECHECK','Повторна перевірка підозрілих відрізків мовлення')
    gap_recheck_v90=inspect_asr_gaps_v90(audio,audio_gap_report,report_dir)
    flags.append('V90_GAP_WINDOWS_RECHECKED_'+str(gap_recheck_v90.get('reported_speech_intervals')))
    flags.append('V90_GAP_ONE_SIDED_MAT_'+str(gap_recheck_v90.get('pending_count')))"""
    new="""    # RG_ASR_SINGLE_AUTO_V1: V90 exists only to re-transcribe RU+UK gaps for
    # profanity. Full-stream profanity censorship is disabled by user choice.
    # Keep V87 acoustic gap evidence, never manufacture a V90 coverage PASS.
    gap_recheck_v90={'schema':'RG_V90_SKIPPED_NO_PROFANITY_CENSORSHIP',
                     'complete':False,'pending_review':[],
                     'verified_intervals':[],'skipped_reason':'MAT_CENSORSHIP_DISABLED'}
    flags.append('V90_PROFANITY_BILINGUAL_RECHECK_SKIPPED_BY_USER_POLICY')"""
    s=edit(s,old,new,"auto_disable_v90")
    s=edit(s,"stage('ASR','Підготовка розпізнавання мовлення та цензури')",
           "stage('ASR','Однопрохідне розпізнавання мовлення для монтажу')","ui_description")
    src[AUTO]=s
    s=src[GATE]
    old="""        elif int(gap.get("suspected") or 0)>0:
            v90=job.get('gap_bilingual_review_v90')
            from rg_fullstream_rescue_mutes_v88 import fingerprint as audio_fingerprint
            if (not isinstance(v90,dict) or v90.get('source')!=audio_fingerprint(job.get('audio'))
                    or not v90.get('complete') or
                    int(v90.get('reported_speech_intervals') or 0)<=0):
                failures.append("V90_SOURCE_BOUND_BILINGUAL_GAP_REVIEW_INCOMPLETE")
            elif int(v90.get('pending_count') or 0)>0:
                warnings.append("V90_PROFANITY_REVIEW_DISABLED_BY_USER")
            else:
                warnings.append("V90_ALL_SILERO_WINDOWS_RECHECKED_NO_UNRESOLVED_MATCHES")"""
    new="""        elif int(gap.get("suspected") or 0)>0:
            # RG_ASR_SINGLE_AUTO_V1: V87 may report uncertain speech.
            # Do not demand RU+UK profanity transcription when mat censorship
            # is disabled; preserve acoustic gap warnings for QA instead.
            warnings.append("V87_UNTRANSCRIBED_SPEECH_REQUIRES_EDITORIAL_REVIEW")"""
    s=edit(s,old,new,"gate_v90_policy")
    src[GATE]=s
    s=src[BATCH]
    for name in [AUTO,GATE]:
        oldhash=sha(original[name])
        newhash=sha(src[name].replace("\n","\r\n").encode("utf-8") if b"\r\n" in original[name] else src[name].encode("utf-8"))
        s=edit(s,oldhash,newhash,"engine_hash_"+name)
    src[BATCH]=s
    # retain each file's on-disk newline convention, source preserving checksum safety
    result={}
    for name in FILES:
        ast.parse(src[name],filename=name)
        result[name]=(src[name].replace("\n","\r\n").encode("utf-8") if b"\r\n" in original[name] else src[name].encode("utf-8"))
    return result
def verify_modified(before,after):
    assert b"LANGS=('auto',)" in after[CHUNK]
    assert b"language=None" in after[CHILD]
    assert b"V90_PROFANITY_BILINGUAL_RECHECK_SKIPPED_BY_USER_POLICY" in after[AUTO]
    assert b"V87_UNTRANSCRIBED_SPEECH_REQUIRES_EDITORIAL_REVIEW" in after[GATE]
    assert sha(after[AUTO]).encode() in after[BATCH]
    assert sha(after[GATE]).encode() in after[BATCH]
    for name in FILES: ast.parse(after[name].decode("utf-8-sig"),filename=name)
def run(install=False):
    original={n:(APP/n).read_bytes() for n in FILES}
    patched=build(original)
    verify_modified(original,patched)
    output("STATIC","PASS","FILES",",".join(FILES))
    if not install:return
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("VIDEO_ACTIVE_ABORT")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_SINGLE_PASS_ASR_V1_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True,exist_ok=False)
    for n,b in original.items():
        f=backup/n;f.write_bytes(b)
        if f.read_bytes()!=b:raise RuntimeError("BACKUP_VERIFY_FAILED_"+n)
    installed=[]
    try:
        if active_workers():raise RuntimeError("WORKER_START_RACE")
        for n in FILES:
            p=APP/n
            if p.read_bytes()!=original[n]:raise RuntimeError("CONCURRENT_MODIFICATION_"+n)
            stage=p.with_suffix(".rg_asr_v1.tmp")
            stage.write_bytes(patched[n])
            if stage.read_bytes()!=patched[n]:raise RuntimeError("TEMP_VERIFY_"+n)
            os.replace(stage,p);installed.append(n)
        for n,b in patched.items():
            if (APP/n).read_bytes()!=b:raise RuntimeError("POST_SHA_FAILED_"+n)
        output("INSTALL","PASS","BACKUP",backup)
    except BaseException:
        for n in reversed(installed):
            (APP/n).write_bytes(original[n])
        output("ROLLBACK","ATTEMPTED",backup)
        raise
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--install",action="store_true")
    run(p.parse_args().install)
