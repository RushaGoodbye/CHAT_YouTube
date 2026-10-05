from __future__ import annotations
import hashlib,json,os,re,shutil,subprocess,sys,tempfile,time,zipfile,py_compile
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNTIME_PY=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
VERSION="0.20.31.0"
PACK="PACK310"
NAME=f"RG_AUTO_EDIT_STUDIO_UPDATE_{VERSION}_{PACK}_LIVE_TELEMETRY.zip"

def _sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def _find_pack300()->Path:
    for p in [
        DATA/"PACKAGES"/"RG_AUTO_EDIT_STUDIO_UPDATE_0.20.30.0_PACK300.zip",
        Path.home()/"Downloads"/"RG_AUTO_EDIT_STUDIO_UPDATE_0.20.30.0_PACK300.zip",
    ]:
        if p.is_file():return p
    raise RuntimeError("PACK300 base archive not found")

def build_auto_edit_pack310_update()->dict:
    if os.name!="nt":raise RuntimeError("Windows only")
    if not APP.is_dir():raise RuntimeError("RG Auto Edit app not found")
    base=_find_pack300()
    with zipfile.ZipFile(base) as z:base_installer=z.read("INSTALL_PACK300.py").decode("utf-8")

    downloads=Path.home()/"Downloads";downloads.mkdir(parents=True,exist_ok=True)
    packages=DATA/"PACKAGES";packages.mkdir(parents=True,exist_ok=True)
    zip_path=downloads/NAME;nas_copy=packages/NAME

    live_module=r'''from __future__ import annotations
import json,os,re,time
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QRectF,QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QFont
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QProgressBar,QListWidget,QListWidgetItem
from rg_pack300_visual import VisualProductionPanel as BasePanel,QAMatrix

BG=QColor("#0F1115");SURF=QColor("#16191F");SURF2=QColor("#1C2027");BORDER=QColor("#292F38")
TEXT=QColor("#EEF2F6");MUTED=QColor("#8A929D");ACCENT=QColor("#6F8FB8");GREEN=QColor("#35C779");YELLOW=QColor("#D5AA47");RED=QColor("#F04F5F")

def _txt(h,n,d="—"):
    try:
        w=getattr(h,n);return w.text() if hasattr(w,"text") else str(w)
    except Exception:return d

def _fmt(sec):
    sec=max(0,int(sec or 0));h,r=divmod(sec,3600);m,s=divmod(r,60);return f"{h:02d}:{m:02d}:{s:02d}"

class StageRail(QFrame):
    STAGES=[("START","СТАРТ"),("CLOCK","ПОШУК"),("DIALOGUE","ДІАЛОГИ"),("XML","XML"),("RELEASE","RELEASE"),("QA","QA"),("DONE","ГОТОВО")]
    def __init__(self,parent=None):
        super().__init__(parent);self.code="START";self.pc=0.0;self.setMinimumHeight(58)
    def set_state(self,code,pc):self.code=str(code or "START").upper();self.pc=float(pc or 0);self.update()
    def _idx(self):
        s=self.code
        if "DONE" in s:return 6
        if "QA" in s or "POST" in s:return 5
        if "RELEASE" in s or "HEALTH" in s or "MANIFEST" in s:return 4
        if "XML" in s or "OUTPUT" in s:return 3
        if "DIALOG" in s:return 2
        if "CLOCK" in s or "SYNC" in s or "WHISPER" in s or "FACE" in s:return 1
        return 0
    def paintEvent(self,e):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        n=len(self.STAGES);left=25;right=max(left+1,self.width()-25);y=20;step=(right-left)/(n-1);idx=self._idx()
        for i in range(n-1):
            x1=left+i*step;x2=left+(i+1)*step;p.setPen(QPen(GREEN if i<idx else BORDER,4,Qt.SolidLine,Qt.RoundCap));p.drawLine(QPointF(x1,y),QPointF(x2,y))
        for i,(_,name) in enumerate(self.STAGES):
            x=left+i*step;c=GREEN if i<idx else ACCENT if i==idx else BORDER
            p.setPen(Qt.NoPen);p.setBrush(c);p.drawEllipse(QPointF(x,y),7,7);p.setPen(TEXT if i<=idx else MUTED);p.setFont(QFont("Segoe UI",6,QFont.Bold));p.drawText(QRectF(x-45,32,90,16),Qt.AlignHCenter,name)

class TelemetryModel:
    def __init__(self,host):
        self.host=host;self.stream="";self.line_count=0;self.exact_pc=None;self.exact_count=0;self.fallback_pc=0.0
        self.stage="START";self.stage_started=time.time();self.last_signal=None;self.last_event="Очікуємо запуску"
        self.outputs=0;self.resume=0;self.cache=0;self.qa="—";self.events=[];self.video="—";self.dialogue="—";self.errors=0
        self.last_visible=0.0
    def reset(self,stream):
        self.stream=stream;self.line_count=0;self.exact_pc=None;self.exact_count=0;self.fallback_pc=0.0;self.stage="START";self.stage_started=time.time()
        self.last_signal=None;self.last_event="Запуск";self.outputs=0;self.resume=0;self.cache=0;self.qa="—";self.events=[];self.video="—";self.dialogue="—";self.errors=0;self.last_visible=0.0
    def _event(self,text):
        text=str(text or "").strip()
        if not text:return
        if not self.events or self.events[0]!=text:self.events.insert(0,text);self.events=self.events[:8]
        self.last_event=text;self.last_signal=time.time()
    def _set_stage(self,stage,floor=None,event=None):
        stage=str(stage or self.stage).upper()
        if stage!=self.stage:self.stage=stage;self.stage_started=time.time()
        if floor is not None:self.fallback_pc=max(self.fallback_pc,float(floor))
        if event:self._event(event)
    def consume(self,line):
        line=str(line or "").strip()
        if not line:return
        now=time.time()
        if line.startswith("RGPROGRESS|"):
            try:
                _,pc,code,msg=line.split("|",3);pc=max(0,min(100,float(pc)))
                first_exact=(self.exact_count==0);self.exact_pc=pc;self.exact_count+=1;\n                if first_exact:self.last_visible=pc\n                self._set_stage(code,pc,msg or code)
                m=re.search(r"video\s+([0-9]+(?:\.[0-9]+)?)\s*min",msg or "",re.I)
                if m:self.video=m.group(1)+" min"
                m=re.search(r"(\d+)/(\d+)",msg or "")
                if m:self.dialogue=m.group(1)+"/"+m.group(2)
                return
            except Exception:pass
        if line.startswith("RGRESUME|CLOCK|READY"):
            self.resume+=1;self.cache+=1;self._set_stage("CLOCK",30,"CLOCK cache - готово");return
        if line.startswith("RGRESUME|DIALOGUE|"):
            self.resume+=1;self.cache+=1
            parts=line.split("|");idx=parts[2] if len(parts)>2 else "?"
            try:n=int(idx);floor=min(68,42+n*12)
            except Exception:floor=54
            self.dialogue=str(idx);self._set_stage("DIALOGUE",floor,f"Діалог {idx} - cache READY");return
        if line.startswith("RGXMLFOLDER|"):
            self._set_stage("XML",8,"Папка XML підготовлена");return
        if line.startswith("RGOUTPUT|") or line.startswith("RGXMLREADY|") or line.startswith("ГОТОВО:"):
            self.outputs+=1;self._set_stage("XML",74,f"XML готово - {self.outputs}");return
        if line.startswith("RGMANIFEST|"):
            self._set_stage("RELEASE",84,"Маніфест готовий");return
        if line.startswith("RGRELEASEHEALTH|"):
            self._set_stage("RELEASE",89,"Release health готовий");return
        if line.startswith("RGPOSTRUN|"):
            self._set_stage("QA",96,"Post-run QA")
            try:
                d=json.loads(line.split("|",1)[1]);passed=bool(d.get("passed"));self.qa="PASS" if passed else "CHECK"
                self.fallback_pc=100.0;self.stage="DONE";self.stage_started=now;self._event("QA "+self.qa)
            except Exception:pass
            return
        if line.startswith("RGPOSTRUNFILE|"):
            self.fallback_pc=max(self.fallback_pc,100.0);self._event("QA report готовий");return
        if line.startswith("PERFORMANCE:"):
            self._event(line[:120]);return
        if "CACHE_HIT" in line.upper():
            self.cache+=1;self._event("Cache hit");return
        if "ERROR" in line.upper() or "ПОМИЛ" in line.upper():
            self.errors+=1;self._event(line[:120]);return
        if line.startswith("СТАРТ:"):
            self._set_stage("START",2,"Backend запущено");return
    def refresh(self):
        stream=_txt(self.host,"metric_stream","").strip()
        if not stream or stream=="—":stream=_txt(self.host,"stream","").strip()
        if stream!=self.stream:self.reset(stream)
        if not stream:return self.snapshot()
        try:
            import rg_studio_ui as ui
            p=Path(ui.APP_DIR)/"run_manifests"/stream/"STUDIO_RUN.log"
            if p.is_file():
                lines=p.read_text(encoding="utf-8",errors="replace").splitlines()
                if len(lines)<self.line_count:self.line_count=0
                for line in lines[self.line_count:]:self.consume(line)
                self.line_count=len(lines)
        except Exception:pass
        active=bool(getattr(self.host,"proc",None))
        if active and self.fallback_pc<2:self.fallback_pc=2
        pc=self.exact_pc if self.exact_pc is not None else self.fallback_pc
        pc=max(self.last_visible,min(100.0,float(pc or 0)));self.last_visible=pc
        started=getattr(self.host,"started_at",None);elapsed=max(0,time.time()-started) if started else 0
        stage_elapsed=max(0,time.time()-self.stage_started)
        source="ТОЧНО • BACKEND" if self.exact_count else ("ОЦІНКА • CACHE/ЕТАПИ" if pc>0 else "ОЧІКУЄ ДАНІ")
        eta=None
        if self.exact_count and pc>=3 and pc<99.5 and elapsed>2:
            eta=elapsed*(100-pc)/pc
        elif hasattr(self.host,"proc_eta_value"):
            t=self.host.proc_eta_value.text().strip()
            if t and t!="—":return self.snapshot(pc,elapsed,stage_elapsed,source,t)
        eta_txt=_fmt(eta) if eta is not None and eta<72*3600 else "обчислюється"
        return self.snapshot(pc,elapsed,stage_elapsed,source,eta_txt)
    def snapshot(self,pc=None,elapsed=0,stage_elapsed=0,source="",eta_txt="обчислюється"):
        if pc is None:pc=self.exact_pc if self.exact_pc is not None else self.fallback_pc
        finish="—"
        if eta_txt not in ("—","обчислюється"):
            try:
                parts=[int(x) for x in eta_txt.split(":")]
                sec=(parts[-3]*3600+parts[-2]*60+parts[-1]) if len(parts)>=3 else 0
                finish=time.strftime("%H:%M:%S",time.localtime(time.time()+sec))
            except Exception:pass
        age="—" if self.last_signal is None else f"{max(0,int(time.time()-self.last_signal))} с"
        return {"pc":float(pc or 0),"elapsed":elapsed,"stage_elapsed":stage_elapsed,"source":source,"eta":eta_txt,"finish":finish,
                "stage":self.stage,"last":self.last_event,"age":age,"outputs":self.outputs,"resume":self.resume,"cache":self.cache,
                "qa":self.qa,"events":list(self.events),"video":self.video,"dialogue":self.dialogue,"exact_count":self.exact_count,"errors":self.errors}

class LiveTelemetryBoard(QFrame):
    def __init__(self,host,parent=None):
        super().__init__(parent);self.host=host;self.model=TelemetryModel(host);self.setObjectName("LiveTelemetryBoard")
        self.setStyleSheet("QFrame#LiveTelemetryBoard{background:#12151A;border:1px solid #303641;border-radius:12px;}")
        root=QVBoxLayout(self);root.setContentsMargins(12,10,12,10);root.setSpacing(8)
        head=QHBoxLayout();title=QLabel("LIVE TELEMETRY");title.setStyleSheet("font-size:10pt;font-weight:800;color:#EEF2F6;");self.source=QLabel("ОЧІКУЄ ДАНІ");self.source.setStyleSheet("padding:4px 8px;border-radius:6px;background:#20242B;color:#AEB6C0;font-weight:700;")
        head.addWidget(title);head.addWidget(self.source);head.addStretch();self.percent=QLabel("0.0%");self.percent.setStyleSheet("font-size:26pt;font-weight:800;color:#6F8FB8;");head.addWidget(self.percent);root.addLayout(head)
        self.bar=QProgressBar();self.bar.setRange(0,1000);self.bar.setValue(0);self.bar.setTextVisible(False);self.bar.setMinimumHeight(14);root.addWidget(self.bar)
        stats=QGridLayout();stats.setHorizontalSpacing(8);stats.setVerticalSpacing(5)
        def mk(name):
            b=QFrame();b.setStyleSheet("background:#181C22;border:1px solid #292F38;border-radius:8px;");l=QVBoxLayout(b);l.setContentsMargins(9,6,9,6);k=QLabel(name);k.setStyleSheet("font-size:7pt;color:#7F8894;");v=QLabel("—");v.setStyleSheet("font-size:11pt;font-weight:750;color:#EEF2F6;");l.addWidget(k);l.addWidget(v);return b,v
        labels=[("МИНУЛО","elapsed"),("ЕТАП","stage"),("ЧАС ЕТАПУ","stage_time"),("ETA","eta"),("ЗАВЕРШЕННЯ","finish"),("ОСТАННІЙ СИГНАЛ","age"),
                ("ДІАЛОГ","dialogue"),("ПОЗИЦІЯ ВІДЕО","video"),("XML ГОТОВО","outputs"),("CACHE/RESUME","cache"),("QA","qa"),("СИГНАЛІВ %","signals")]
        self.vals={}
        for i,(name,key) in enumerate(labels):
            b,v=mk(name);self.vals[key]=v;stats.addWidget(b,i//6,i%6)
        root.addLayout(stats)
        self.rail=StageRail(self);root.addWidget(self.rail)
        low=QHBoxLayout();left=QVBoxLayout();self.last=QLabel("Остання подія: —");self.last.setStyleSheet("color:#C7CDD5;font-weight:650;");self.last.setWordWrap(True);left.addWidget(self.last)
        self.integrity=QLabel("Джерело прогресу: —");self.integrity.setStyleSheet("color:#8A929D;");left.addWidget(self.integrity);low.addLayout(left,2)
        self.events=QListWidget();self.events.setMaximumHeight(92);low.addWidget(self.events,3);root.addLayout(low)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(250);self.refresh()
    def refresh(self):
        d=self.model.refresh();pc=d["pc"];approx=not bool(d["exact_count"]) and pc>0
        self.percent.setText(("≈ " if approx else "")+f"{pc:.1f}%");self.bar.setValue(int(round(pc*10)));self.source.setText(d["source"])
        self.vals["elapsed"].setText(_fmt(d["elapsed"]));self.vals["stage"].setText(d["stage"].replace("_"," "))
        self.vals["stage_time"].setText(_fmt(d["stage_elapsed"]));self.vals["eta"].setText(d["eta"]);self.vals["finish"].setText(d["finish"]);self.vals["age"].setText(d["age"])
        self.vals["dialogue"].setText(str(d["dialogue"]));self.vals["video"].setText(str(d["video"]));self.vals["outputs"].setText(str(d["outputs"]))
        self.vals["cache"].setText(f"{d['cache']} / {d['resume']}");self.vals["qa"].setText(str(d["qa"]));self.vals["signals"].setText(str(d["exact_count"]))
        self.rail.set_state(d["stage"],pc);self.last.setText("Остання подія: "+str(d["last"]));self.integrity.setText("Прогрес: "+d["source"]+" • помилок "+str(d["errors"]))
        self.events.clear()
        for x in d["events"][:6]:self.events.addItem(QListWidgetItem(x))
        # Keep all legacy/new visual layers synchronized.
        try:
            self.host.metric_elapsed.setText(_fmt(d["elapsed"]))
            self.host.progress.setRange(0,1000);self.host.progress.setValue(int(round(pc*10)))
            self.host.percent.setText(("≈ " if approx else "")+f"{pc:.1f}%")
            if d["eta"]!="обчислюється":self.host.proc_eta_value.setText(d["eta"])
        except Exception:pass

class VisualProductionPanel(BasePanel):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.live_board=LiveTelemetryBoard(host,self);self.layout().insertWidget(0,self.live_board)
        try:self.timer.setInterval(1000)
        except Exception:pass
    def refresh(self):
        if not self.isVisible():return
        try:super().refresh()
        except Exception:pass
'''

    installer="from __future__ import annotations\nBASE_INSTALLER="+repr(base_installer)+"\nPACK310_LIVE="+repr(live_module)+"\n"+r'''
import json,os,re,shutil,sys,time,traceback,py_compile
from pathlib import Path
APP=Path.cwd()
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
if os.environ.get("RG_PACK310_DRYRUN"):DATA=APP/"_PACK310_DATA"
VERSION="0.20.31.0"

def atomic(p,text):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+".pack310.tmp");t.write_text(text,encoding="utf-8");os.replace(t,p)

def snapshot():
    root=DATA/"release_backups"/("PRE_PACK310_"+time.strftime("%Y%m%d_%H%M%S"));root.mkdir(parents=True,exist_ok=True)
    names=["rg_studio_ui.py","rg_auto_edit_config.json","rg_studio_version.py","rg_pack300_visual.py","rg_pack310_live_visual.py","rg_pack310_selftest.py"]
    ex={}
    for n in names:
        p=APP/n;ex[n]=p.exists()
        if p.is_file():shutil.copy2(p,root/n)
    (root/"_existed.json").write_text(json.dumps(ex),encoding="utf-8");return root,ex

def restore(root,ex):
    for n,was in ex.items():
        src=root/n;dst=APP/n
        if src.is_file():shutil.copy2(src,dst)
        elif not was and dst.exists():
            try:dst.unlink()
            except Exception:pass

def apply_pack300():
    ns={"__name__":"rg_pack300_embedded","__file__":str(APP/"<embedded_pack300>")};exec(compile(BASE_INSTALLER,"<embedded_pack300>","exec"),ns);rc=ns["main"]()
    if rc not in (0,None):raise RuntimeError("Embedded PACK300 failed: "+str(rc))

def patch_config():
    p=APP/"rg_auto_edit_config.json";d=json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
    d["pack310"]={"schema":"RG_PACK310_LIVE_TELEMETRY_V1","enabled":True,"version":VERSION,
      "live_progress":{"exact_backend":True,"cache_resume_fallback":True,"approximation_marked":True,"monotonic":True,"log_driven":True},
      "timers":{"elapsed_exact":True,"stage_elapsed":True,"last_signal_age":True,"refresh_ms":250},
      "eta":{"exact_when_backend_progress":True,"fallback_label_when_unknown":True,"finish_clock":True},
      "signals":{"rgprogress":True,"rgresume":True,"rgoutput":True,"rgmanifest":True,"rgreleasehealth":True,"rgpostrun":True},
      "visual":{"prominent_percent":True,"progress_bar":True,"stage_rail":True,"event_feed":True,"source_badge":True,"dialogue":True,"video_position":True,"xml_ready":True,"cache_resume":True,"qa":True},
      "safety":{"no_fake_exact_percent":True,"core_editing_untouched":True,"original_source_direct_locked":True}}
    atomic(p,json.dumps(d,ensure_ascii=False,indent=2))

def patch_ui():
    p=APP/"rg_studio_ui.py";s=p.read_text(encoding="utf-8")
    s=s.replace("from rg_pack300_visual import VisualProductionPanel,QAMatrix","from rg_pack310_live_visual import VisualProductionPanel,QAMatrix")
    s=s.replace("from rg_pack170_visual import VisualProductionPanel,QAMatrix","from rg_pack310_live_visual import VisualProductionPanel,QAMatrix")
    if "from rg_pack310_live_visual import VisualProductionPanel,QAMatrix" not in s:
        anchor="from rg_pack160_style import PACK160_CSS\n"
        if anchor in s:s=s.replace(anchor,anchor+"from rg_pack310_live_visual import VisualProductionPanel,QAMatrix\n",1)
        else:raise RuntimeError("PACK310 import anchor missing")
    # Fix 0-1000 scale final value.
    s=s.replace('self.progress.setValue(100);self.percent.setText("100%")','self.progress.setValue(1000);self.percent.setText("100%")')
    # Keep post-run stage informative even before QA finishes.
    if "RG_PACK310_QA_PROGRESS" not in s:
        anchor='    def _start_postrun_qa(self):\n'
        if anchor in s:
            repl='    def _start_postrun_qa(self):\n        # RG_PACK310_QA_PROGRESS\n        try:\n            self.progress.setRange(0,1000);self.progress.setValue(max(self.progress.value(),920));self.percent.setText("≈ 92.0%");self.proc_eta_value.setText("QA...")\n        except Exception:pass\n'
            s=s.replace(anchor,repl,1)
    if "RG_PACK310_QA_FINAL_PROGRESS" not in s:
        anchor='        passed=bool(result and result.get("passed") and int(code)==0)\n'
        if anchor in s:s=s.replace(anchor,anchor+'        # RG_PACK310_QA_FINAL_PROGRESS\n        try:self.progress.setRange(0,1000);self.progress.setValue(1000);self.percent.setText("100.0%")\n        except Exception:pass\n',1)
    atomic(p,s)

def patch_version():
    p=APP/"rg_studio_version.py";s=p.read_text(encoding="utf-8") if p.is_file() else ""
    s=re.sub(r'STUDIO_VERSION\s*=\s*"[^"]+"',f'STUDIO_VERSION="{VERSION}"',s)
    if "STUDIO_VERSION" not in s:s='STUDIO_VERSION="'+VERSION+'"\n'+s
    if "RG_FEATURE_PACK" in s:s=re.sub(r'RG_FEATURE_PACK\s*=\s*"[^"]+"','RG_FEATURE_PACK="PACK310"',s)
    else:s+='\nRG_FEATURE_PACK="PACK310"\n'
    if "RG_PACK310_SCHEMA" not in s:s+='\nRG_PACK310_SCHEMA="RG_PACK310_LIVE_TELEMETRY_V1"\n'
    atomic(p,s)

def write_selftest():
    code="""from __future__ import annotations
import json,py_compile
from pathlib import Path
APP=Path(__file__).resolve().parent
def main():
    checks=[]
    def add(n,ok,d=""):checks.append({"name":n,"ok":bool(ok),"detail":str(d)})
    for n in ["rg_studio_ui.py","rg_pack300_visual.py","rg_pack310_live_visual.py","rg_studio_postrun.py"]:
        try:py_compile.compile(str(APP/n),doraise=True);add("compile "+n,True)
        except Exception as e:add("compile "+n,False,e)
    ui=(APP/"rg_studio_ui.py").read_text(encoding="utf-8",errors="replace")
    add("pack310 import","from rg_pack310_live_visual import VisualProductionPanel,QAMatrix" in ui)
    add("final progress scale","self.progress.setValue(1000)" in ui)
    add("qa progress hook","RG_PACK310_QA_PROGRESS" in ui)
    cfg=json.loads((APP/"rg_auto_edit_config.json").read_text(encoding="utf-8-sig"));add("live telemetry enabled",bool((cfg.get("pack310") or {}).get("enabled")))
    passed=all(x["ok"] for x in checks);print("RG_PACK310_SELFTEST|"+json.dumps({"passed":passed,"result":"READY FOR PRODUCTION" if passed else "BLOCKED","checks":checks},ensure_ascii=False));return 0 if passed else 3
if __name__=="__main__":raise SystemExit(main())
"""
    atomic(APP/"rg_pack310_selftest.py",code)

def main():
    b,ex=snapshot()
    try:
        apply_pack300();atomic(APP/"rg_pack310_live_visual.py",PACK310_LIVE);patch_config();patch_ui();patch_version();write_selftest()
        for n in ["rg_studio_ui.py","rg_pack300_visual.py","rg_pack310_live_visual.py","rg_pack310_selftest.py","rg_studio_version.py"]:
            if (APP/n).is_file():py_compile.compile(str(APP/n),doraise=True)
        print("PACK310_BACKUP|"+str(b));print("PACK310_INSTALL|PASS");return 0
    except Exception:
        traceback.print_exc();restore(b,ex);print("PACK310_INSTALL|ROLLBACK");return 10
if __name__=="__main__":raise SystemExit(main())
'''

    notes="""RG Auto Edit PACK310 - Live Telemetry Hotfix

Причина проблеми 891:
- STUDIO_RUN.log: RGPROGRESS=0, RGHEARTBEAT=0, RGETA=0.
- Прогін пішов через cache/resume: RGRESUME CLOCK + RGRESUME DIALOGUE.
- Старий visual layer залежав від RGPROGRESS, тому live % не мав джерела.
- elapsed timer був у прихованій legacy-картці, а не в новому visual layer.
- фінальний progress мав scale bug: 100 записувалось у шкалу 0-1000.

Що виправлено:
- Live Telemetry читає STUDIO_RUN.log незалежно від RGPROGRESS.
- Точний % використовується, коли backend його віддає.
- Cache/resume отримує чесний stage-based approximate progress з позначкою ОЦІНКА.
- exact elapsed timer 00:00:00.
- stage elapsed timer.
- last signal age.
- ETA і expected finish clock, коли є достатні точні дані.
- current stage, dialogue, video position, ready XML, cache/resume count, QA, signal count.
- stage rail and last-events feed.
- синхронізація legacy/new progress widgets.
- final 1000/1000 progress scale fix.
- post-run QA progress 92% -> 100%.

Пакет кумулятивний: всередині PACK300, PACK200 і PACK170.
"""

    with tempfile.TemporaryDirectory(prefix="rg_pack310_build_") as td:
        td=Path(td);root=td/"RG_PACK310";root.mkdir()
        inst=root/"INSTALL_PACK310.py";inst.write_text(installer,encoding="utf-8")
        rn=root/"RELEASE_NOTES_PACK310.txt";rn.write_text(notes,encoding="utf-8")
        dry=td/"dry_app";shutil.copytree(APP,dry,dirs_exist_ok=True)
        env=os.environ.copy();env.update({"RG_PACK170_DRYRUN":"1","RG_PACK200_DRYRUN":"1","RG_PACK300_DRYRUN":"1","RG_PACK310_DRYRUN":"1","PYTHONUTF8":"1"})
        cp=subprocess.run([sys.executable,"-X","utf8",str(inst)],cwd=str(dry),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=300)
        if cp.returncode!=0:raise RuntimeError("PACK310 dry-run failed: "+(cp.stdout or "")[-12000:]+(cp.stderr or "")[-12000:])
        for n in ["rg_studio_ui.py","rg_pack300_visual.py","rg_pack310_live_visual.py","rg_pack310_selftest.py"]:py_compile.compile(str(dry/n),doraise=True)
        smoke_py=str(RUNTIME_PY if RUNTIME_PY.is_file() else Path(sys.executable));pe={**env,"QT_QPA_PLATFORM":"offscreen","RG_AUTO_EDIT_BACKEND":str(dry)}
        sm=subprocess.run([smoke_py,"-X","utf8","-c","import rg_pack310_live_visual,rg_studio_ui;print('IMPORT_OK')"],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=80)
        if sm.returncode!=0 or "IMPORT_OK" not in (sm.stdout or ""):raise RuntimeError("PACK310 import smoke failed: "+(sm.stdout or "")[-8000:]+(sm.stderr or "")[-8000:])
        # Reproduce 891: no RGPROGRESS, cache/resume only.
        logdir=dry/"run_manifests"/"891";logdir.mkdir(parents=True,exist_ok=True)
        (logdir/"STUDIO_RUN.log").write_text("\n".join([
          "СТАРТ: backend 891","RGXMLFOLDER|"+str(dry/"891"),"RGRESUME|CLOCK|READY|cached clock/boundary stage reused",
          "RGRESUME|DIALOGUE|1|READY|reuse completed dialogue XML","ГОТОВО: "+str(dry/"891"/"RG_EDITED_891.xml"),
          "RGMANIFEST|x","RGRELEASEHEALTH|x"
        ])+"\n",encoding="utf-8")
        probe=dry/"_pack310_probe.py"
        probe.write_text("""import os,time,json
os.environ["QT_QPA_PLATFORM"]="offscreen";os.environ["RG_AUTO_EDIT_BACKEND"]=os.getcwd()
from PySide6.QtWidgets import QApplication
from rg_studio_ui import StudioWindow
app=QApplication([]);w=StudioWindow();w.resize(1920,1080);w.show();app.processEvents()
w.metric_stream.setText("891");w.started_at=time.time()-12
b=w.visual_panel.live_board
for _ in range(4):b.refresh();app.processEvents()
approx=b.percent.text();elapsed=b.vals["elapsed"].text();source=b.source.text();stage=b.vals["stage"].text()
ok=("≈" in approx and float(approx.replace("≈","").replace("%","").strip())>0 and elapsed!="00:00:00" and "ОЦІНКА" in source and stage!="START")
p=os.path.join(os.getcwd(),"run_manifests","891","STUDIO_RUN.log")
with open(p,"a",encoding="utf-8") as f:f.write("RGPROGRESS|42.5|WHISPER|video 12.4 min 1/3\\n")
for _ in range(3):b.refresh();app.processEvents()
exact=b.percent.text();source2=b.source.text()
ok=ok and exact.startswith("42.5") and "ТОЧНО" in source2
pix=w.grab();shot=os.path.join(os.getcwd(),"PACK310_LIVE_TELEMETRY_1920x1080.png");saved=pix.save(shot);ok=ok and saved
print("PACK310_PROBE|"+json.dumps({"passed":ok,"approx":approx,"elapsed":elapsed,"source":source,"stage":stage,"exact":exact,"source2":source2,"screenshot":shot},ensure_ascii=False))
raise SystemExit(0 if ok else 7)
""",encoding="utf-8")
        up=subprocess.run([smoke_py,"-X","utf8",str(probe)],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=100)
        if up.returncode!=0 or "PACK310_PROBE|" not in (up.stdout or ""):raise RuntimeError("PACK310 replay/UI probe failed: "+(up.stdout or "")[-10000:]+(up.stderr or "")[-10000:])
        preview=dry/"PACK310_LIVE_TELEMETRY_1920x1080.png";shutil.copy2(preview,root/preview.name)
        st=subprocess.run([smoke_py,"-X","utf8",str(dry/"rg_pack310_selftest.py")],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=70)
        if st.returncode!=0 or "READY FOR PRODUCTION" not in (st.stdout or ""):raise RuntimeError("PACK310 selftest failed: "+(st.stdout or "")[-7000:]+(st.stderr or "")[-7000:])
        files=[]
        for p in [inst,rn,root/preview.name]:files.append({"path":p.name,"sha256":_sha(p),"size":p.stat().st_size})
        manifest={"schema":"RG_UPDATE_MANIFEST_V2","product":"RG Auto Edit Studio","studio_version":VERSION,"channel":"STABLE","summary":"PACK310 Live Telemetry: exact elapsed timer, exact/fallback progress, cache/resume visualization, stage timer, ETA, event feed and final scale fix.","created_at":time.time(),"files":files,"core_modified":False,"ui_only":True,"expected_ui_change":True,"base":"embedded PACK300","safety":{"original_source_direct_locked":True,"replay_891_required":True,"rollback":True}}
        (root/"RG_UPDATE_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
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
    return {"status":"READY","version":VERSION,"pack":PACK,"zip":str(zip_path),"nas_copy":str(nas_copy),"size":zip_path.stat().st_size,"sha256":_sha(zip_path),
            "dry_run":"PASS","compile":"PASS","import_smoke":"PASS","replay_891_no_rgprogress":"PASS","exact_progress_replay":"PASS","elapsed_timer":"PASS","ui_preview":"IN_ZIP","selftest":"READY FOR PRODUCTION","crc":"PASS","manifest":"PASS","installed":False}
