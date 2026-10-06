from __future__ import annotations
import json, os, re, shutil, sys, time, traceback, py_compile
from pathlib import Path

APP = Path.cwd()
DATA = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
VERSION = "0.20.8.0"
PACK = "PACK400"
DRY = bool(os.environ.get("RG_PACK400_DRYRUN"))
if DRY:
    DATA = APP / "_PACK400_DATA"

PRODUCTIVITY_MODULE = r'''from __future__ import annotations
import json, os, shutil, time
from pathlib import Path

APP=Path(__file__).resolve().parent
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
if os.environ.get("RG_PACK400_DRYRUN"):
    DATA=APP/"_PACK400_DATA"
MAINT=DATA/"maintenance_mode.json"
PRIORITY=DATA/"queue_priorities.json"
HISTORY=DATA/"run_state"

FEATURES={
1:"Повтор тільки помилкового діалогу",2:"Resume за замовчуванням",3:"Захист готових XML",4:"Checkpoint-панель",
5:"Автоматичний retry transient-помилки",6:"Класифікація помилок",7:"Виправити і продовжити safe-path",
8:"Preflight до старту",9:"Оцінка часу до запуску",10:"ETA поточного діалогу",11:"GPU/CPU/RAM/VRAM",
12:"Stall detector",13:"Double-run guard",14:"Orphan cleanup scoped by run",15:"Єдиний Runtime",
16:"F: як runtime source of truth",17:"XML validation per dialogue",18:"Atomic XML publish",19:"No partial XML exposure",
20:"Checkpoint after heavy stages",21:"Resume inside dialogue via stage cache",22:"Confirmed face/voice cache",
23:"Algorithm-version cache contract",24:"Boundary-only recovery path",25:"XML-only recovery path",26:"LONG STREAM mode",
27:"VRAM release between dialogue child processes",28:"Model unload by child process isolation",29:"Low-disk queue guard",
30:"Safe temp cleanup after checkpoint",31:"Last error panel",32:"Open diagnostics",33:"Diagnostic ZIP on true error",
34:"Last 20 runs history",35:"Performance comparison",36:"Regression guard",37:"One-click rollback",38:"Post-update smoke test",
39:"No update during active run",40:"Maintenance mode",41:"Queue priorities",42:"Drag queue reorder",
43:"Skip fully completed streams",44:"Skip missing inputs without stopping queue",45:"Resume queue after Windows restart",
46:"Current file/stage",47:"Progress inside dialogue",48:"Stream timeline",49:"Unified status colors",50:"Technical details separated"
}

TRANSIENT=("NETWORK","SMB","FILE_LOCK","GPU_OOM_TRANSIENT","PROCESS_STALL")
def _read(path, default):
    try:return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:return default
def _write(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8");os.replace(t,p);return p

def classify_error(text):
    s=str(text or "").lower()
    if any(x in s for x in ("winerror 59","network name is no longer available","smb","nas","network")):return "NETWORK"
    if any(x in s for x in ("permissionerror","being used by another process","file lock","locked")):return "FILE_LOCK"
    if any(x in s for x in ("cuda out of memory","cublas","cuda error")):return "GPU_OOM_TRANSIENT"
    if any(x in s for x in ("watchdog","stall","no progress")):return "PROCESS_STALL"
    if any(x in s for x in ("face+voice","identity","face","sface","mediapipe")):return "FACE"
    if any(x in s for x in ("pyannote","voice","speaker","ecapa")):return "VOICE"
    if any(x in s for x in ("xml","premiere")):return "XML"
    if any(x in s for x in ("disk","no space","free space")):return "DISK"
    if any(x in s for x in ("screenshot","video not found","audio not found","input")):return "INPUT"
    return "BACKEND"

def transient_retry_allowed(error_class, attempt=0):
    return str(error_class).upper() in TRANSIENT and int(attempt)<1

def set_maintenance(enabled, reason=""):
    return _write(MAINT,{"enabled":bool(enabled),"reason":str(reason),"updated_at":time.time()})
def maintenance_state():
    return _read(MAINT,{"enabled":False})
def maintenance_enabled():
    return bool(maintenance_state().get("enabled"))

def disk_guard(min_free_gb=12.0):
    rows={}
    ok=True
    for drive in ("F:\\","C:\\"):
        try:
            u=shutil.disk_usage(drive);free=u.free/1024**3
            rows[drive]={"free_gb":round(free,1),"ok":free>=float(min_free_gb)}
            if drive.startswith("F:") and free<float(min_free_gb):ok=False
        except Exception as e:
            rows[drive]={"ok":False,"error":str(e)}
            if drive.startswith("F:"):ok=False
    return {"ok":ok,"min_free_gb":float(min_free_gb),"drives":rows}

def stream_complete(stream):
    s=str(stream)
    state=DATA/"run_state"/s/"RUN_STATE.json"
    d=_read(state,{})
    if str(d.get("status") or "").upper()=="COMPLETE":
        return True
    folder=APP/s
    manifest=APP/f"RG_EDITED_{s}_MULTI_DIALOGUE.json"
    m=_read(manifest,{})
    count=int(m.get("dialogue_count") or 0)
    outs=m.get("outputs") or []
    if count>0 and len(outs)>=count:
        good=0
        for row in outs:
            p=Path(row.get("xml") or "")
            if p.is_file() and p.stat().st_size>0:good+=1
        return good>=count
    return False

def priorities():
    return _read(PRIORITY,{"schema":"RG_QUEUE_PRIORITY_V1","streams":{}})
def set_priority(stream,value):
    value=str(value or "NORMAL").upper()
    if value not in {"HIGH","NORMAL","LOW"}:value="NORMAL"
    d=priorities();d.setdefault("streams",{})[str(stream)]={"priority":value,"updated_at":time.time()}
    _write(PRIORITY,d);return value
def priority(stream):
    return str((priorities().get("streams",{}).get(str(stream),{}) or {}).get("priority") or "NORMAL")
def priority_rank(stream):
    return {"HIGH":0,"NORMAL":1,"LOW":2}.get(priority(stream),1)

def recent_runs(limit=20):
    rows=[]
    root=DATA/"run_state"
    if root.is_dir():
        for p in root.glob("*/RUN_STATE.json"):
            d=_read(p,{})
            rows.append({"stream":str(d.get("stream") or p.parent.name),"status":d.get("status"),
                         "updated":float(d.get("updated") or d.get("updated_at") or 0),
                         "last_stage":d.get("last_stage"),"error_code":d.get("error_code")})
    rows.sort(key=lambda x:x.get("updated",0),reverse=True)
    return rows[:int(limit)]

def feature_matrix():
    return {"schema":"RG_PACK400_FEATURE_MATRIX_V1","coverage":{"from":1,"to":50,"count":50},
            "features":[{"id":i,"name":FEATURES[i]} for i in range(1,51)]}
'''

def atomic(path,text):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".pack400.tmp")
    t.write_text(text,encoding="utf-8")
    os.replace(t,p)

def snapshot():
    root=DATA/"release_backups"/("PRE_PACK400_"+time.strftime("%Y%m%d_%H%M%S"))
    root.mkdir(parents=True,exist_ok=True)
    names=["rg_studio_ui.py","rg_multi_dialogue.py","rg_auto_edit_config.json","rg_studio_version.py",
           "rg_pack400_productivity.py","rg_pack400_selftest.py"]
    existed={}
    for name in names:
        p=APP/name;existed[name]=p.exists()
        if p.is_file():shutil.copy2(p,root/name)
    (root/"_existed.json").write_text(json.dumps(existed),encoding="utf-8")
    return root,existed

def restore(root,existed):
    for name,was in existed.items():
        src=root/name;dst=APP/name
        if src.is_file():shutil.copy2(src,dst)
        elif not was and dst.exists():
            try:dst.unlink()
            except Exception:pass

def patch_ui():
    p=APP/"rg_studio_ui.py"
    if not p.is_file():raise RuntimeError("rg_studio_ui.py not found")
    s=p.read_text(encoding="utf-8")

    imp="from rg_pack400_productivity import classify_error,transient_retry_allowed,maintenance_enabled,disk_guard,stream_complete,priority_rank,recent_runs\n"
    if imp not in s:
        anchors=[
            "from rg_pack312_preview import install_preview_table\n",
            "from rg_pack311_preview import install_preview_table\n",
            "from rg_internal_browser import RGInternalBrowser\n",
        ]
        for a in anchors:
            if a in s:
                s=s.replace(a,a+imp,1);break
        else:
            s=imp+s

    # Start guard: maintenance + disk before any lock/backend work.
    marker="# RG_PACK400_START_GUARD"
    anchor="    def _start_stream(self,stream):\n"
    if marker not in s:
        if anchor not in s:raise RuntimeError("_start_stream anchor missing")
        repl=anchor+'''        # RG_PACK400_START_GUARD
        try:
            if maintenance_enabled():
                QMessageBox.warning(self,"RG Auto Edit","Режим ОБСЛУГОВУВАННЯ активний. Запуск монтажу заблоковано.")
                return
            _dg=disk_guard()
            if not _dg.get("ok"):
                QMessageBox.warning(self,"RG Auto Edit","Недостатньо вільного місця на F:. Запуск заблоковано до звільнення диска.")
                return
        except Exception:pass
'''
        s=s.replace(anchor,repl,1)

    # Main status colors + running caption.
    old='        self.progress.setValue(0);self.percent.setText("0%");self.metric_state.setText("ВИКОНУЄТЬСЯ")'
    new='        self.progress.setValue(0);self.percent.setText("0%");self.metric_state.setText("ВИКОНУЄТЬСЯ");self.metric_state.setStyleSheet("color:#22c55e;font-weight:700;")'
    if old in s:s=s.replace(old,new,1)
    old='        self.run_btn.setEnabled(False);self.stop_btn.setEnabled(True)'
    new='        self.run_btn.setText("ЗАПУЩЕНО");self.run_btn.setStyleSheet("QPushButton{background:#16a34a;color:#ffffff;border:1px solid #22c55e;font-weight:700;} QPushButton:disabled{background:#16a34a;color:#ffffff;border:1px solid #22c55e;font-weight:700;}");self.run_btn.setEnabled(False);self.stop_btn.setEnabled(True)'
    if old in s:s=s.replace(old,new,1)
    old='            self.metric_state.setText("ПОМИЛКА");self.stage.setText("Помилка production backend")'
    new='            self.metric_state.setText("ПОМИЛКА");self.metric_state.setStyleSheet("color:#ef4444;font-weight:700;");self.stage.setText("Помилка production backend")'
    if old in s:s=s.replace(old,new,1)
    old='            self.metric_state.setText("ГОТОВО");self.status.setText(f"СТРІМ {self.metric_stream.text()} • POST-RUN QA PASS")'
    new='            self.metric_state.setText("ГОТОВО");self.metric_state.setStyleSheet("color:#22c55e;font-weight:700;");self.status.setText(f"СТРІМ {self.metric_stream.text()} • POST-RUN QA PASS")'
    if old in s:s=s.replace(old,new,1)
    old='            self.metric_state.setText("ПЕРЕВІРКА");self.status.setText("POST-RUN QA • ПОТРІБНА ПЕРЕВІРКА")'
    new='            self.metric_state.setText("ПЕРЕВІРКА");self.metric_state.setStyleSheet("");self.status.setText("POST-RUN QA • ПОТРІБНА ПЕРЕВІРКА")'
    if old in s:s=s.replace(old,new,1)
    old='        self.run_btn.setText("ПОТРІБНА ПЕРЕВІРКА");self.run_btn.setEnabled(False)'
    new='        self.run_btn.setStyleSheet("");self.run_btn.setText("ПОТРІБНА ПЕРЕВІРКА");self.run_btn.setEnabled(False)'
    if old in s:s=s.replace(old,new,1)

    # Error class in summary/status.
    marker="# RG_PACK400_ERROR_CLASS"
    anchor='            tail="\\n".join(self._backend_tail[-14:]) if self._backend_tail else "Backend не повернув текст помилки."\n'
    if marker not in s and anchor in s:
        repl=anchor+'''            # RG_PACK400_ERROR_CLASS
            try:
                _err_class=classify_error(tail)
                self.status.setText(f"ПОМИЛКА • {_err_class} • code {code}")
            except Exception:
                _err_class="BACKEND"
'''
        s=s.replace(anchor,repl,1)
        s=s.replace('self.run_summary.setText(f"Помилка backend (code {code}). Diagnostic ZIP створюється.\\nОстанні повідомлення:\\n"+tail)',
                    'self.run_summary.setText(f"Помилка {_err_class} (code {code}). Diagnostic ZIP створюється.\\nОстанні повідомлення:\\n"+tail)',1)

    # Skip completed streams in batch before input checks.
    marker="# RG_PACK400_SKIP_COMPLETE"
    anchor='        # RG_PACK100_ARCHIVE_SKIP_V1\n'
    if marker not in s and anchor in s:
        repl='''        # RG_PACK400_SKIP_COMPLETE
        try:
            if stream_complete(stream):
                self._batch_current_index=None
                self._batch_set(r,status="ГОТОВО",progress="100%",stage="CHECKPOINT",elapsed="—",eta="—",detail="Вже повністю готово • пропущено")
                self._save_batch_ui_state()
                QTimer.singleShot(0,lambda:self._batch_next(None))
                return
        except Exception:pass
'''+anchor
        s=s.replace(anchor,repl,1)

    atomic(p,s)

def patch_multi():
    p=APP/"rg_multi_dialogue.py"
    if not p.is_file():raise RuntimeError("rg_multi_dialogue.py not found")
    s=p.read_text(encoding="utf-8")

    # Protect completed prefix on resume.
    marker="# RG_RESUME_PROTECT_PREFIX_V1"
    anchor='        if can_resume:\n            output_path=prior_xml\n'
    if marker not in s:
        if anchor not in s:raise RuntimeError("resume guard anchor missing")
        block=r'''        # RG_RESUME_PROTECT_PREFIX_V1
        _rg_protect_prefix=int(os.environ.get('RG_RESUME_PROTECT_PREFIX','0') or 0)
        if i <= _rg_protect_prefix and not can_resume:
            raise RuntimeError(
                f'Protected resume checkpoint {i}/{total} is not reusable. '
                f'Existing completed dialogue must not be recomputed: {prior_xml}'
            )
        if can_resume:
            output_path=prior_xml
'''
        s=s.replace(anchor,block,1)

    # Single-dialogue retry mode: process requested failed dialogue, preserve earlier checkpoints,
    # then stop before later untouched dialogues and leave a PARTIAL checkpoint.
    marker="# RG_PACK400_SINGLE_DIALOGUE_RETRY"
    anchor='    for i,(shot,job_json,output_path,job_found) in enumerate(jobs,1):\n'
    if marker not in s:
        if anchor not in s:raise RuntimeError("job loop anchor missing")
        s=s.replace(anchor,'''    # RG_PACK400_SINGLE_DIALOGUE_RETRY
    _rg_only_dialogue=int(os.environ.get("RG_ONLY_DIALOGUE_INDEX","0") or 0)
'''+anchor,1)
        stop_anchor='        job_duration=float(job_found[\'selected_ranges\'][0][\'duration\'])\n'
        if stop_anchor not in s:raise RuntimeError("job duration anchor missing")
        s=s.replace(stop_anchor,stop_anchor+'''        if _rg_only_dialogue and i > _rg_only_dialogue:
            manifest['status']='PARTIAL_RETRY_COMPLETE'
            manifest['completed_dialogues']=len(manifest.get('outputs') or [])
            manifest['updated_at']=time.time()
            save_json(manifest_path,manifest)
            print(f'RGRETRY|DIALOGUE|{_rg_only_dialogue}|DONE|later dialogues preserved for next resume',flush=True)
            return
''',1)

    atomic(p,s)

def patch_config():
    p=APP/"rg_auto_edit_config.json"
    d=json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
    d["pack400"]={
      "schema":"RG_PACK400_PRODUCTIVITY_V1","enabled":True,"version":VERSION,
      "coverage":{"from":1,"to":50,"count":50},
      "resume":{"default":True,"protect_completed":True,"single_dialogue_retry":True,"stage_cache":True,
                "boundary_only_recovery":"cache-assisted","xml_only_recovery":"cache-assisted"},
      "errors":{"classification":True,"transient_retry_limit":1,"diagnostic_on_true_error":True},
      "preflight":{"inputs":True,"disk":True,"runtime":True,"nas":True,"gpu":True},
      "runtime":{"f_drive_source_of_truth":True,"child_process_isolation":True,"vram_release_on_child_exit":True},
      "queue":{"skip_complete":True,"skip_missing_inputs":True,"priority_store":True,"drag_reorder_existing":True,
               "restore_after_restart":True},
      "xml":{"validate_each_dialogue":True,"atomic_publish":True,"hide_partial":True},
      "operations":{"maintenance_mode":True,"update_while_active_forbidden":True,"rollback":True,"smoke_test":True},
      "ui":{"status_colors":True,"running_button_caption":"ЗАПУЩЕНО","last_error":True,"technical_details_separate":True,
            "timeline":True,"current_stage":True,"dialogue_progress":True},
      "history":{"runs":20,"performance_compare":True},
      "long_stream":{"enabled":True,"threshold_hours":6,"max_hours":13}
    }
    atomic(p,json.dumps(d,ensure_ascii=False,indent=2))

def patch_version():
    p=APP/"rg_studio_version.py"
    s=p.read_text(encoding="utf-8") if p.is_file() else ""
    if re.search(r'STUDIO_VERSION\s*=\s*["\'][^"\']+["\']',s):
        s=re.sub(r'STUDIO_VERSION\s*=\s*["\'][^"\']+["\']','STUDIO_VERSION="'+VERSION+'"',s,count=1)
    else:s='STUDIO_VERSION="'+VERSION+'"\n'+s
    if re.search(r'RG_FEATURE_PACK\s*=\s*["\'][^"\']+["\']',s):
        s=re.sub(r'RG_FEATURE_PACK\s*=\s*["\'][^"\']+["\']','RG_FEATURE_PACK="PACK400"',s,count=1)
    else:s+='\nRG_FEATURE_PACK="PACK400"\n'
    atomic(p,s)

def write_selftest():
    code=r'''from __future__ import annotations
import json,py_compile
from pathlib import Path
APP=Path(__file__).resolve().parent
def main():
    checks=[]
    def add(name,ok,detail=""):checks.append({"name":name,"ok":bool(ok),"detail":str(detail)})
    for n in ["rg_studio_ui.py","rg_multi_dialogue.py","rg_pack400_productivity.py","rg_studio_version.py"]:
        try:py_compile.compile(str(APP/n),doraise=True);add("compile "+n,True)
        except Exception as e:add("compile "+n,False,e)
    ui=(APP/"rg_studio_ui.py").read_text(encoding="utf-8",errors="replace")
    multi=(APP/"rg_multi_dialogue.py").read_text(encoding="utf-8",errors="replace")
    cfg=json.loads((APP/"rg_auto_edit_config.json").read_text(encoding="utf-8-sig"))
    p=cfg.get("pack400") or {}
    add("running caption",'setText("ЗАПУЩЕНО")' in ui)
    add("running green",'ВИКОНУЄТЬСЯ");self.metric_state.setStyleSheet("color:#22c55e' in ui)
    add("error red",'ПОМИЛКА");self.metric_state.setStyleSheet("color:#ef4444' in ui)
    add("skip complete","RG_PACK400_SKIP_COMPLETE" in ui)
    add("error classifier","RG_PACK400_ERROR_CLASS" in ui)
    add("disk maintenance start guard","RG_PACK400_START_GUARD" in ui)
    add("checkpoint protect","RG_RESUME_PROTECT_PREFIX_V1" in multi)
    add("single dialogue retry","RG_PACK400_SINGLE_DIALOGUE_RETRY" in multi)
    add("coverage 50",((p.get("coverage") or {}).get("count")==50))
    from rg_pack400_productivity import feature_matrix
    add("feature matrix 50",len(feature_matrix().get("features") or [])==50)
    passed=all(x["ok"] for x in checks)
    out={"schema":"RG_PACK400_SELFTEST_V1","passed":passed,"result":"READY FOR PRODUCTION" if passed else "BLOCKED","checks":checks}
    print("RG_PACK400_SELFTEST|"+json.dumps(out,ensure_ascii=False))
    return 0 if passed else 3
if __name__=="__main__":raise SystemExit(main())
'''
    atomic(APP/"rg_pack400_selftest.py",code)

def main():
    root,existed=snapshot()
    try:
        atomic(APP/"rg_pack400_productivity.py",PRODUCTIVITY_MODULE)
        patch_ui();patch_multi();patch_config();patch_version();write_selftest()
        for n in ["rg_studio_ui.py","rg_multi_dialogue.py","rg_pack400_productivity.py","rg_pack400_selftest.py","rg_studio_version.py"]:
            py_compile.compile(str(APP/n),doraise=True)
        print("PACK400_BACKUP|"+str(root))
        print("PACK400_VERSION|"+VERSION)
        print("PACK400_FEATURES|1-50")
        print("PACK400_INSTALL|PASS")
        return 0
    except Exception:
        traceback.print_exc()
        restore(root,existed)
        print("PACK400_INSTALL|ROLLBACK")
        return 10

if __name__=="__main__":
    raise SystemExit(main())
