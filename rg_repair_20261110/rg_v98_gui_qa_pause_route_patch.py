"""RG Full Stream V9.8: redirect paused editorial QA recheck to explicit
review-only MP4 with human confirmation, and preserve publication BLOCK.

This is a Studio GUI fix, NOT a standalone render or a QA override.
Only installs while worker IDLE; makes versioned rollback backup.
"""
from pathlib import Path
import os,sys,ast,json,hashlib,time,uuid,argparse
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
UI="rg_fullstream_manual_tab_v4.py"
ENGINE="rg_fullstream_batch_v53.py"
SHA_UI="15f2a6c3af05517a173874e91362a758d31680a47b11e49f9647072180439b42"
SHA_ENGINE="6ca774eee691420b3e481ca7fcda9a6fc403f643bb5476f01e00a62b08356bc7"
OLD="""    def on_recheck():
        try:
            from rg_fullstream_launcher_v2 import enqueue_recheck
            value=_stream(number.text())
            result=enqueue_recheck(value)"""
NEW="""    def on_recheck():
        try:
            from rg_fullstream_launcher_v2 import enqueue_recheck
            value=_stream(number.text())
            # RG_QA_PAUSE_RECHECK_V98: never loop through a normal render
            # after an editorial QA pause; offer a separate QA-only copy.
            # Only an explicit click+confirmation in Studio can launch it.
            from rg_fullstream_batch_v53 import resume_selected
            from rg_fullstream_qa_export_v96 import arm_existing_review_request
            from rg_fullstream_process_state_v59 import worker_lock_state
            state_path=DATA/'fullstream_v2'/value/'status.json'
            current=_read_json(state_path) if state_path.is_file() else {}
            if current.get('state')=='PAUSED_EDITORIAL_QA':
                if worker_lock_state(DATA)!='IDLE':
                    raise RuntimeError('WORKER_ACTIVE_NO_QA_RECHECK')
                approval=QMessageBox.question(page,'Окремий MP4 для перевірки QA',
                    'Стрім '+value+' зупинено на редакційному QA.\\\\n'
                    'Створити окремий MP4 ТІЛЬКИ ДЛЯ ПЕРЕВІРКИ?\\\\n'
                    'Заборона публікації та невирішені перевірки збережуться.\\\\n'
                    'Попередні MP4 та результати ASR залишаться без змін.',
                    QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
                if approval!=QMessageBox.Yes:return
                request=DATA/'fullstream_v2'/value/'queue_request.json'
                if not request.is_file():
                    queued=enqueue_recheck(value,app=APP,data=DATA,create_worker=False)
                    if queued.get('state')!='QUEUED':
                        raise RuntimeError('QA_RECHECK_ENQUEUE_FAILED:'+str(queued))
                armed=arm_existing_review_request(value,app=APP,data=DATA)
                selected=resume_selected(value,app=APP,data=DATA)
                details.setText('QA-копія '+value+' • PID '+str(selected['pid'])+
                    ' • ПУБЛІКАЦІЮ ЗАБОРОНЕНО • '
                    +str(armed.get('state'))+' • лише у Studio')
                refresh()
                return
            result=enqueue_recheck(value)"""
def sha(data):return hashlib.sha256(data).hexdigest()
def encode(original,decoded):
    ast.parse(decoded)
    encoded=decoded.replace("\r\n","\n").encode("utf-8")
    if b"\r\n" in original:encoded=encoded.replace(b"\n",b"\r\n")
    if original.startswith(b"\xef\xbb\xbf"):encoded=b"\xef\xbb\xbf"+encoded
    return encoded
def prepare():
    old={n:(APP/n).read_bytes() for n in (UI,ENGINE)}
    if sha(old[UI])!=SHA_UI or sha(old[ENGINE])!=SHA_ENGINE:
        raise RuntimeError("PRODUCTION_MODULE_CHANGED_SHA256_REFUSE")
    src=old[UI].decode("utf-8-sig").replace("\r\n","\n")
    if src.count(OLD)!=1:raise RuntimeError("ON_RECHECK_ANCHOR_CHANGED")
    revised=src.replace(OLD,NEW,1)
    # Escape actual newline only. QMessageBox receives intentional \n
    revised=revised.replace("QA.\\\\n'","QA.\\n'") if False else revised
    ui_new=encode(old[UI],revised)
    engine=old[ENGINE].decode("utf-8-sig").replace("\r\n","\n")
    if engine.count(SHA_UI)!=1:raise RuntimeError("ONE_AND_ONLY_ONE_GUI_SHA_PIN_REQUIRED")
    engine_new=encode(old[ENGINE],engine.replace(SHA_UI,sha(ui_new),1))
    for name,content in ((UI,ui_new),(ENGINE,engine_new)):
        ast.parse(content.decode("utf-8-sig"))
    if b"RG_QA_PAUSE_RECHECK_V98" not in ui_new:
        raise RuntimeError("PATCH_NOT_APPLIED")
    return old,{UI:ui_new,ENGINE:engine_new}
def static_acceptance(new):
    import importlib.util,copy
    sys.path.insert(0,str(APP))
    from rg_fullstream_qa_export_v96 import evaluate
    from rg_fullstream_editorial_gate_v82 import validate
    root=DATA/"fullstream_v2"/"895"
    plan=json.loads((root/"processing_plan.json").read_text(encoding="utf-8-sig"))
    gate=validate(plan)
    assert gate["decision"]=="BLOCK" and gate["blocking_reasons"]==["NOTIFICATION_COVERAGE_UNVERIFIED"]
    allowed=evaluate(dict(plan,qa_preview_export_requested=True),gate)
    assert allowed["allow_review_render"] is True
    assert allowed["publish_ready"] is False and allowed["archive_allowed"] is False
    rejected=evaluate(dict(plan,qa_preview_export_requested=False),gate)
    assert rejected["allow_review_render"] is False
    # Negative technical and source-scan guards.
    invalid=dict(gate,blocking_reasons=["ASR_WORD_TIMESTAMPS_MISSING"])
    assert not evaluate(dict(plan,qa_preview_export_requested=True),invalid)["allow_review_render"]
    no_scan=dict(plan,extra_review_flags=[])
    assert not evaluate(dict(no_scan,qa_preview_export_requested=True),gate)["allow_review_render"]
    assert len(plan["popup_masks"])==21
    src=new[UI].decode("utf-8-sig")
    node=ast.parse(src)
    guards=("worker_lock_state(DATA)!='IDLE'","QMessageBox.question","arm_existing_review_request(value,app=APP,data=DATA)","resume_selected(value,app=APP,data=DATA)")
    for guard in guards:
        if guard not in src:raise RuntimeError("MISSING_GUI_GUARD_"+guard)
    print("RGV98|895_QA_PREVIEW_ELIGIBLE|PASS",flush=True)
    print("RGV98|PUBLISH_ARCHIVE_BLOCK_RETAINED|PASS",flush=True)
    print("RGV98|NEGATIVE_NO_CONSENT_TECHNICAL_AND_SCAN_CONTROLS|PASS",flush=True)
    print("RGV98|GUI_AND_ENGINE_SHA_PINS_UPDATED|PASS",flush=True)
def install():
    old,new=prepare()
    static_acceptance(new)
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":raise RuntimeError("WORKER_ACTIVE_DEFER_INSTALL")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_V98_GUI_QA_PAUSE_ROUTING_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True,exist_ok=False)
    for n in old:
        (backup/n).write_bytes(old[n])
        assert sha((backup/n).read_bytes())==sha(old[n])
    applied=[]
    try:
        if active_workers() or worker_lock_state(DATA)!="IDLE":
            raise RuntimeError("WORKER_STARTED_DEFER_INSTALL")
        for n in (UI,ENGINE):
            p=APP/n
            if p.read_bytes()!=old[n]:raise RuntimeError("CONCURRENT_SOURCE_CHANGE")
            tmp=p.with_name(p.name+".v98.tmp")
            tmp.write_bytes(new[n])
            if sha(tmp.read_bytes())!=sha(new[n]):raise RuntimeError("STAGED_SHA_MISMATCH")
            os.replace(tmp,p)
            applied.append(n)
        if any((APP/n).read_bytes()!=new[n] for n in (UI,ENGINE)):
            raise RuntimeError("POST_INSTALL_SHA_FAILURE")
        print("RGV98|INSTALLED|PASS|BACKUP|"+str(backup),flush=True)
        print("RGV98|RESTART_STUDIO_REQUIRED|TRUE",flush=True)
        print("RGV98|NO_RENDER_OR_QUEUE_MODIFICATION|PASS",flush=True)
    except:
        for n in reversed(applied):(APP/n).write_bytes(old[n])
        print("RGV98|ROLLBACK|ATTEMPTED",flush=True)
        raise
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--install",action="store_true")
    args=parser.parse_args()
    if args.install:install()
    else:
        _,new=prepare()
        static_acceptance(new)
        print("RGV98|DRYRUN|PASS",flush=True)
if __name__=="__main__":main()
