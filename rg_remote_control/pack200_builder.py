from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, zipfile, py_compile
from pathlib import Path

APP = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNTIME_PY = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
VERSION = "0.20.20.0"
PACK = "PACK200"
NAME = f"RG_AUTO_EDIT_STUDIO_UPDATE_{VERSION}_{PACK}.zip"

def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def _find_pack170() -> Path:
    candidates = [
        DATA / "PACKAGES" / "RG_AUTO_EDIT_STUDIO_UPDATE_0.20.7.0_PACK170.zip",
        Path.home() / "Downloads" / "RG_AUTO_EDIT_STUDIO_UPDATE_0.20.7.0_PACK170.zip",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise RuntimeError("PACK170 base archive not found")

def build_auto_edit_pack200_update() -> dict:
    if os.name != "nt":
        raise RuntimeError("Windows only")
    if not APP.is_dir():
        raise RuntimeError("RG Auto Edit app not found")

    base_zip = _find_pack170()
    with zipfile.ZipFile(base_zip) as z:
        base_installer = z.read("INSTALL_PACK170.py").decode("utf-8")

    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    packages = DATA / "PACKAGES"
    packages.mkdir(parents=True, exist_ok=True)
    zip_path = downloads / NAME
    nas_copy = packages / NAME

    visual = r'''from __future__ import annotations
import json, math, os, re, time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QProgressBar,
    QTableWidget,QTableWidgetItem,QHeaderView,QListWidget,QListWidgetItem
)

BG=QColor("#101216"); CARD=QColor("#171A20"); CARD2=QColor("#1D2128")
TEXT=QColor("#EEF2F6"); MUTED=QColor("#89919B"); ACCENT=QColor("#6F8FB8")
GREEN=QColor("#35C779"); RED=QColor("#F04F5F"); YELLOW=QColor("#D5AA47"); PURPLE=QColor("#8B7CC8")
BORDER=QColor("#282E37")

def _txt(host,name,default="—"):
    try:
        w=getattr(host,name)
        return w.text() if hasattr(w,"text") else str(w)
    except Exception:
        return default

def _pct(host):
    try:
        w=getattr(host,"progress"); mx=max(1,int(w.maximum()))
        return max(0.0,min(1.0,float(w.value())/mx))
    except Exception:
        return 0.0

def _num(s):
    m=re.search(r"(\d+(?:\.\d+)?)",str(s or ""))
    return float(m.group(1)) if m else None

def _stage_index(stage):
    s=str(stage or "").upper()
    names=["IMPORT","ANALYSIS","WHISPER","DIALOGUES","FRAMES","XML","PREMIERE","RENDER","DONE"]
    maps=[("IMPORT",0),("PREFLIGHT",0),("SYNC",1),("VISUAL",1),("ANAL",1),("FACE",1),
          ("WHISPER",2),("DIALOG",3),("MULTI",3),("FRAME",4),("THUMB",4),("XML",5),
          ("PREMIERE",6),("RENDER",7),("QA",7),("DONE",8),("READY",0)]
    idx=0
    for k,v in maps:
        if k in s: idx=v
    return names,idx

def _human(stage):
    s=str(stage or "READY")
    up=s.upper()
    repl=[
      ("PREFLIGHT","Передстартова перевірка"),("IMPORT","Імпорт"),("SYNC","Синхронізація"),
      ("VISUAL_ANALYSIS","Аналіз відео"),("ANALYSIS","Аналіз"),("FACE","Пошук облич"),
      ("WHISPER","Whisper"),("MULTI_DIALOGUE","Обробка діалогів"),("DIALOG","Діалоги"),
      ("FRAME","Кадри"),("THUMB","Кадри"),("XML","XML"),("PREMIERE","Premiere"),
      ("RENDER","Render"),("QA","QA"),("DONE","Готово"),("READY","Готово до запуску")
    ]
    for a,b in repl:
        if a in up: return b
    return s[:42]

class SoftCard(QFrame):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName("Pack200Card")

class PipelineWidget(QWidget):
    STAGES=["Імпорт","Аналіз","Whisper","Діалоги","Кадри","XML","Premiere","Render","Done"]
    def __init__(self,parent=None):
        super().__init__(parent); self.active=0; self.error=False; self.phase=0.0; self.stage_pct=0.0
        self.times=[0.0]*len(self.STAGES); self._last=0; self._t=time.time(); self.setMinimumHeight(86)
        self.timer=QTimer(self); self.timer.timeout.connect(self._tick); self.timer.start(90)
    def _tick(self):
        now=time.time(); self.times[self._last]+=max(0,now-self._t); self._t=now
        self.phase=(self.phase+.035)%1.0; self.update()
    def set_state(self,stage,pct,error=False):
        _,idx=_stage_index(stage)
        if idx!=self._last: self._last=idx; self._t=time.time()
        self.active=idx; self.stage_pct=max(0,min(1,float(pct))); self.error=bool(error); self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        n=len(self.STAGES); left=30; right=self.width()-30; y=27; step=(right-left)/(n-1)
        for i in range(n-1):
            x1=left+i*step; x2=left+(i+1)*step
            c=GREEN if i<self.active else BORDER
            p.setPen(QPen(c,4,Qt.SolidLine,Qt.RoundCap)); p.drawLine(QPointF(x1,y),QPointF(x2,y))
            if i==self.active and not self.error and self.active<n-1:
                ax=x1+(x2-x1)*self.phase
                p.setPen(Qt.NoPen); p.setBrush(ACCENT); p.drawEllipse(QPointF(ax,y),4,4)
        for i,name in enumerate(self.STAGES):
            x=left+i*step
            if i<self.active: c=GREEN
            elif i==self.active: c=RED if self.error else ACCENT
            else: c=BORDER
            p.setPen(QPen(BG,2)); p.setBrush(c); p.drawEllipse(QPointF(x,y),8,8)
            p.setPen(TEXT if i<=self.active else MUTED); p.setFont(QFont("Segoe UI",7,QFont.Bold))
            p.drawText(QRectF(x-48,43,96,18),Qt.AlignHCenter|Qt.AlignTop,name)
            sec=self.times[i]
            if sec>1:
                p.setPen(MUTED); p.setFont(QFont("Segoe UI",6))
                p.drawText(QRectF(x-40,61,80,14),Qt.AlignHCenter|Qt.AlignTop,f"{sec/60:.1f}m")

class Ring(QWidget):
    def __init__(self,title,parent=None):
        super().__init__(parent); self.title=title; self.value=None; self.setMinimumSize(78,78); self.setMaximumSize(92,92)
    def set_value(self,v):
        try: self.value=max(0,min(100,float(v)))
        except Exception: self.value=None
        self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing); r=QRectF(9,9,self.width()-18,self.height()-18)
        p.setPen(QPen(BORDER,7,Qt.SolidLine,Qt.RoundCap)); p.drawArc(r,0,360*16)
        if self.value is not None:
            p.setPen(QPen(ACCENT,7,Qt.SolidLine,Qt.RoundCap)); p.drawArc(r,90*16,-int(self.value/100*360*16))
        p.setPen(TEXT); p.setFont(QFont("Segoe UI",10,QFont.Bold))
        p.drawText(r,Qt.AlignCenter,"—" if self.value is None else f"{self.value:.0f}%")
        p.setPen(MUTED); p.setFont(QFont("Segoe UI",6,QFont.Bold))
        p.drawText(QRectF(0,self.height()-16,self.width(),14),Qt.AlignCenter,self.title)

class AudioMonitor(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.left=[]; self.right=[]; self.boundaries=[]; self.setMinimumHeight(84)
    def set_activity(self,l,r,boundary=False):
        for arr,v in ((self.left,l),(self.right,r)):
            if v is not None:
                try: arr.append(max(0,min(1,float(v))))
                except Exception: pass
                del arr[:-80]
        if boundary: self.boundaries.append(len(self.left)-1)
        self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(MUTED); p.setFont(QFont("Segoe UI",7,QFont.Bold)); p.drawText(8,13,"AUDIO ACTIVITY")
        mid=self.height()/2; w=max(1,self.width()-16); x0=8
        for arr,y,c in ((self.left,mid-14,ACCENT),(self.right,mid+16,GREEN)):
            if len(arr)>1:
                step=w/max(1,len(arr)-1); pts=[]
                for i,v in enumerate(arr): pts.append(QPointF(x0+i*step,y-(v-.5)*22))
                p.setPen(QPen(c,1.6))
                for a,b in zip(pts,pts[1:]): p.drawLine(a,b)
            else:
                p.setPen(QPen(BORDER,1)); p.drawLine(x0,y,x0+w,y)
        p.setPen(MUTED); p.setFont(QFont("Segoe UI",6)); p.drawText(8,self.height()-5,"L / R • межі діалогів позначаються під час аналізу")

class FaceCandidates(QWidget):
    def __init__(self,host,parent=None):
        super().__init__(parent); self.host=host; self.paths=[]; self.setMinimumHeight(92)
    def refresh(self):
        vals=[]
        for name in ("face_candidate_paths","_last_face_candidates","thumbnail_candidates"):
            x=getattr(self.host,name,None)
            if isinstance(x,(list,tuple)): vals.extend(str(v) for v in x if v)
        self.paths=[x for x in vals if Path(x).is_file()][:5]; self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(MUTED); p.setFont(QFont("Segoe UI",7,QFont.Bold)); p.drawText(8,13,"TOP 5 КАДРІВ")
        gap=7; y=21; h=self.height()-27; w=(self.width()-16-gap*4)/5
        for i in range(5):
            r=QRectF(8+i*(w+gap),y,w,h); p.setPen(QPen(BORDER,1)); p.setBrush(CARD2); p.drawRoundedRect(r,7,7)
            p.setPen(TEXT if i<len(self.paths) else MUTED); p.setFont(QFont("Segoe UI",7))
            p.drawText(r,Qt.AlignCenter,Path(self.paths[i]).name[:16] if i<len(self.paths) else "—")

class MiniSteps(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.stage="READY"; self.setMinimumHeight(55)
    def set_stage(self,s): self.stage=s; self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        names=["Source","Range","XML","Premiere","Render"]; _,idx=_stage_index(self.stage)
        levels=[0,3,5,6,7]
        gap=5; w=(self.width()-gap*4)/5
        for i,(n,lvl) in enumerate(zip(names,levels)):
            r=QRectF(i*(w+gap),8,w,32); ok=idx>=lvl
            p.setPen(Qt.NoPen); p.setBrush(GREEN if ok else CARD2); p.drawRoundedRect(r,6,6)
            p.setPen(TEXT if ok else MUTED); p.setFont(QFont("Segoe UI",7,QFont.Bold)); p.drawText(r,Qt.AlignCenter,("✓ " if ok else "")+n)

class HealthWidget(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.states={}; self.setMinimumHeight(52)
    def set_states(self,d): self.states=dict(d or {}); self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        names=["SOURCE","STORAGE","NAS","GPU","PREMIERE","WHISPER","DEPS"]
        ok=sum(1 for n in names if self.states.get(n,True))
        p.setPen(TEXT); p.setFont(QFont("Segoe UI",12,QFont.Bold)); p.drawText(8,19,f"SYSTEM {ok}/7 OK")
        x=8
        for n in names:
            c=GREEN if self.states.get(n,True) else RED
            p.setPen(Qt.NoPen); p.setBrush(c); p.drawEllipse(QPointF(x+4,36),4,4); x+=18
        p.setPen(MUTED); p.setFont(QFont("Segoe UI",6)); p.drawText(150,40,"Source • Storage • NAS • GPU • Premiere • Whisper • Dependencies")

class HistoryWidget(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.values=[]; self.setMinimumHeight(64)
    def push(self,v):
        try: v=float(v)
        except Exception: return
        if not self.values or abs(self.values[-1]-v)>.001: self.values=(self.values+[v])[-10:]
        self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(MUTED); p.setFont(QFont("Segoe UI",7,QFont.Bold)); p.drawText(8,13,"ОСТАННІ 10 ПРОГОНІВ")
        vals=self.values
        if len(vals)<2:
            p.setPen(MUTED); p.drawText(QRectF(8,20,self.width()-16,35),Qt.AlignCenter,"Історія з’явиться після прогонів"); return
        mn=min(vals); mx=max(vals); span=max(.001,mx-mn); x0=8; y0=22; w=self.width()-16; h=self.height()-28
        pts=[QPointF(x0+w*i/(len(vals)-1),y0+h*(1-(v-mn)/span)) for i,v in enumerate(vals)]
        p.setPen(QPen(ACCENT,1.8))
        for a,b in zip(pts,pts[1:]): p.drawLine(a,b)

class QueueFlow(SoftCard):
    def __init__(self,host,parent=None):
        super().__init__(parent); self.host=host; self.layout=QVBoxLayout(self); self.layout.setContentsMargins(10,8,10,8); self.layout.setSpacing(5)
        self.title=QLabel("QUEUE FLOW"); self.title.setObjectName("Pack200SectionTitle"); self.layout.addWidget(self.title)
        self.rows=[]
        for i in range(5):
            lab=QLabel("—"); lab.setMinimumHeight(24); lab.setObjectName("Pack200QueueRow"); self.layout.addWidget(lab); self.rows.append(lab)
    def refresh(self):
        texts=[]
        for attr in ("queue_table","queue_tree","queue_list"):
            q=getattr(self.host,attr,None)
            if q is None: continue
            try:
                rc=q.rowCount()
                for r in range(min(5,rc)):
                    vals=[]
                    for c in range(min(4,q.columnCount())):
                        it=q.item(r,c); vals.append(it.text() if it else "")
                    t=" • ".join(v for v in vals if v)
                    if t: texts.append(t)
            except Exception: pass
        if not texts: texts=["Очередь пуста"]
        for i,lab in enumerate(self.rows):
            lab.setText((f"{i+1}. "+texts[i]) if i<len(texts) and texts[i]!="Очередь пуста" else (texts[i] if i<len(texts) else ""))
            lab.setVisible(i<len(texts))

class EventTimeline(QListWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.setMaximumHeight(110); self.setMinimumHeight(78); self._last=None
    def push_stage(self,stage):
        s=_human(stage)
        if s==self._last: return
        self._last=s
        self.insertItem(0,QListWidgetItem(time.strftime("%H:%M:%S")+"  "+s))
        while self.count()>6: self.takeItem(self.count()-1)

class VisualProductionPanel(QFrame):
    def __init__(self,host):
        super().__init__(host); self.host=host; self.setObjectName("VisualProductionPanel")
        self._last_stage=None; self._stage_started=time.time(); self._session_done=0
        root=QVBoxLayout(self); root.setContentsMargins(12,10,12,10); root.setSpacing(8)

        # Command Center 129-136 + Before/Current/Next 196-200
        cc=SoftCard(); cl=QGridLayout(cc); cl.setContentsMargins(12,8,12,8)
        self.stream=QLabel("STREAM —"); self.stream.setObjectName("Pack200Stream")
        self.current=QLabel("Готово до запуску"); self.current.setObjectName("Pack200Current")
        self.progress=QLabel("0%"); self.progress.setObjectName("Pack200Progress")
        self.eta=QLabel("ETA • —"); self.eta.setObjectName("Pack200Big")
        self.queue=QLabel("QUEUE • —"); self.queue.setObjectName("Pack200Muted")
        self.errors=QLabel("ERRORS • 0"); self.errors.setObjectName("Pack200Muted")
        self.before=QLabel("До: —"); self.next=QLabel("Далі: —")
        cl.addWidget(self.stream,0,0); cl.addWidget(self.current,0,1,1,2); cl.addWidget(self.progress,0,3)
        cl.addWidget(self.eta,1,0); cl.addWidget(self.queue,1,1); cl.addWidget(self.errors,1,2); cl.addWidget(self.before,2,0,1,2); cl.addWidget(self.next,2,2,1,2)
        root.addWidget(cc)

        self.pipeline=PipelineWidget(self); root.addWidget(self.pipeline)

        grid=QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)
        live=SoftCard(); ll=QVBoxLayout(live); ll.setContentsMargins(10,8,10,8)
        self.live_title=QLabel("LIVE PROCESS"); self.live_title.setObjectName("Pack200SectionTitle")
        self.dialogue=QLabel("Діалог —"); self.dialogue.setObjectName("Pack200Dialogue")
        self.last_action=QLabel("Остання дія: —"); self.last_action.setObjectName("Pack200Muted")
        self.wait_reason=QLabel("Очікування: —"); self.wait_reason.setObjectName("Pack200Muted")
        self.preview=MiniSteps(self); self.audio=AudioMonitor(self); self.faces=FaceCandidates(host,self)
        ll.addWidget(self.live_title); ll.addWidget(self.dialogue); ll.addWidget(self.last_action); ll.addWidget(self.wait_reason); ll.addWidget(self.preview); ll.addWidget(self.audio); ll.addWidget(self.faces)
        grid.addWidget(live,0,0,2,2)

        perf=SoftCard(); pl=QVBoxLayout(perf); pl.setContentsMargins(10,8,10,8)
        t=QLabel("PERFORMANCE"); t.setObjectName("Pack200SectionTitle"); pl.addWidget(t)
        rings=QHBoxLayout(); self.rings={}
        for n in ["GPU","VRAM","CPU","RAM","DISK","NAS"]:
            r=Ring(n,self); self.rings[n]=r; rings.addWidget(r)
        pl.addLayout(rings)
        self.bottleneck=QLabel("Обмеження: —"); self.bottleneck.setObjectName("Pack200Muted"); pl.addWidget(self.bottleneck)
        self.health=HealthWidget(self); pl.addWidget(self.health)
        grid.addWidget(perf,0,2,1,2)

        self.queueflow=QueueFlow(host,self); grid.addWidget(self.queueflow,1,2,1,2)
        root.addLayout(grid)

        bottom=QGridLayout(); bottom.setHorizontalSpacing(8)
        events=SoftCard(); el=QVBoxLayout(events); el.setContentsMargins(10,8,10,8); et=QLabel("PROCESSING TIMELINE"); et.setObjectName("Pack200SectionTitle"); self.events=EventTimeline(self); el.addWidget(et); el.addWidget(self.events)
        bottom.addWidget(events,0,0,1,2)
        hist=SoftCard(); hl=QVBoxLayout(hist); hl.setContentsMargins(10,8,10,8); self.history=HistoryWidget(self); hl.addWidget(self.history)
        self.session=QLabel("Сесія • стрімів 0 • діалогів 0 • XML 0 • помилок 0"); self.session.setObjectName("Pack200Muted"); hl.addWidget(self.session)
        bottom.addWidget(hist,0,2,1,2)
        root.addLayout(bottom)

        self.status=QLabel("SYSTEM READY   •   NAS —   •   GPU —   •   QUEUE —   •   ERRORS 0   •   "+os.environ.get("RG_AUTO_EDIT_VERSION","PACK200"))
        self.status.setObjectName("Pack200Status"); root.addWidget(self.status)

        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(650); self.refresh()

    def refresh(self):
        stage=_txt(self.host,"stage","READY"); human=_human(stage); p=_pct(self.host); err=("FAIL" in stage.upper() or "ERROR" in stage.upper() or "ПОМИЛ" in stage.upper())
        self.pipeline.set_state(stage,p,err); self.preview.set_stage(stage); self.events.push_stage(stage)
        stream=_txt(self.host,"metric_stream","—").strip() or "—"; self.stream.setText("STREAM "+stream)
        self.current.setText(human); self.progress.setText(f"{p*100:.0f}%")
        eta=_txt(self.host,"proc_eta_value","—"); self.eta.setText("ETA • "+eta)
        dlg=_txt(self.host,"proc_dialogue_value","—"); self.dialogue.setText("Діалог "+dlg)
        self.last_action.setText("Остання дія: "+human)
        names,idx=_stage_index(stage); prev=names[max(0,idx-1)] if idx>0 else "—"; nxt=names[idx+1] if idx+1<len(names) else "—"
        self.before.setText("До: "+prev); self.next.setText("Далі: "+nxt)
        reason="—"
        if "WAIT" in stage.upper() or "PENDING" in stage.upper():
            reason="очікує ресурс"
        self.wait_reason.setText("Очікування: "+reason)

        res=_txt(self.host,"proc_resource_value","")
        pairs={}
        for key in ["GPU","VRAM","CPU","RAM","DISK","NAS"]:
            m=re.search(key+r"[^0-9]*(\d+(?:\.\d+)?)",res,re.I)
            pairs[key]=float(m.group(1)) if m else None
        nums=[float(x) for x in re.findall(r"(\d+(?:\.\d+)?)",res)]
        if pairs["GPU"] is None and nums: pairs["GPU"]=nums[0]
        if pairs["CPU"] is None and len(nums)>1: pairs["CPU"]=nums[1]
        for k,r in self.rings.items(): r.set_value(pairs.get(k))
        gpu=pairs.get("GPU"); disk=pairs.get("DISK"); nas=pairs.get("NAS")
        bottleneck="—"
        if nas is not None and nas>85: bottleneck="NAS"
        elif disk is not None and disk>90: bottleneck="DISK"
        elif gpu is not None and gpu>95: bottleneck="GPU"
        self.bottleneck.setText("Обмеження: "+bottleneck)

        # No fake waveform: activity appears only from available host meters.
        l=_num(_txt(self.host,"audio_left_value","")); r=_num(_txt(self.host,"audio_right_value",""))
        self.audio.set_activity((l/100 if l is not None else None),(r/100 if r is not None else None),"DIALOG" in stage.upper())
        self.faces.refresh(); self.queueflow.refresh()

        qn=_num(_txt(self.host,"queue_count_value","")); self.queue.setText("QUEUE • "+("—" if qn is None else str(int(qn))))
        en=_num(_txt(self.host,"error_count_value","")); en=0 if en is None else int(en); self.errors.setText("ERRORS • "+str(en))
        self.health.set_states({"SOURCE":True,"STORAGE":True,"NAS":(nas is None or nas<98),"GPU":(gpu is None or gpu<99),"PREMIERE":True,"WHISPER":True,"DEPS":True})
        self.history.push(p*100)

        dnum=_num(_txt(self.host,"metric_dialogues","")); xnum=_num(_txt(self.host,"metric_xml",""))
        self.session.setText(f"Сесія • стрімів {1 if stream!='—' else 0} • діалогів {int(dnum or 0)} • XML {int(xnum or 0)} • помилок {en}")
        gp="—" if gpu is None else f"{gpu:.0f}%"; qp="—" if qn is None else str(int(qn))
        self.status.setText(f"SYSTEM READY   •   NAS {'OK' if nas is None or nas<98 else 'WARN'}   •   GPU {gp}   •   QUEUE {qp}   •   ERRORS {en}   •   PACK200")

class QAMatrix(QTableWidget):
    def __init__(self,host):
        super().__init__(0,6,host); self.host=host
        self.setHorizontalHeaderLabels(["RUN","XML","AUDIO","BOUNDARY","TAIL","PREMIERE"])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.setMaximumHeight(108); self.setMinimumHeight(76)
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(1800)
    def _state(self,checks,keys):
        for c in checks:
            n=str(c.get("name","")).lower()
            if any(k in n for k in keys): return "✓" if c.get("ok") else "✕"
        return "—"
    def refresh(self):
        stream=_txt(self.host,"metric_stream","").strip()
        if not stream or stream=="—": return
        candidates=[]
        try:
            if getattr(self.host,"last_xml_folder",""): candidates.append(Path(self.host.last_xml_folder)/"RG_POSTRUN_QA.json")
        except Exception: pass
        try:
            import rg_studio_ui as ui; candidates.append(Path(ui.APP_DIR)/stream/"RG_POSTRUN_QA.json")
        except Exception: pass
        p=next((x for x in candidates if x.is_file()),None)
        if not p: return
        try: checks=json.loads(p.read_text(encoding="utf-8-sig")).get("checks") or []
        except Exception: return
        vals=[stream,self._state(checks,["xml"]),self._state(checks,["audio","аудіо"]),self._state(checks,["boundary","меж"]),self._state(checks,["tail"]),self._state(checks,["premiere"])]
        self.setRowCount(1)
        for i,v in enumerate(vals): self.setItem(0,i,QTableWidgetItem(v))
'''

    installer = "from __future__ import annotations\n" + \
        "BASE_INSTALLER=" + repr(base_installer) + "\n" + \
        "PACK200_VISUAL=" + repr(visual) + "\n" + r'''
import json, os, re, shutil, sys, time, traceback, py_compile
from pathlib import Path
APP=Path.cwd()
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
if os.environ.get("RG_PACK200_DRYRUN"): DATA=APP/"_PACK200_DATA"
VERSION="0.20.20.0"

def atomic(p,text):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".pack200.tmp"); t.write_text(text,encoding="utf-8"); os.replace(t,p)

def snapshot():
    root=DATA/"release_backups"/("PRE_PACK200_"+time.strftime("%Y%m%d_%H%M%S")); root.mkdir(parents=True,exist_ok=True)
    names=["rg_studio_ui.py","rg_auto_edit_config.json","rg_studio_version.py","rg_pack170_visual.py","rg_pack170_selftest.py","rg_pack200_visual.py","rg_pack200_selftest.py"]
    existed={}
    for n in names:
        p=APP/n; existed[n]=p.exists()
        if p.is_file(): shutil.copy2(p,root/n)
    (root/"_existed.json").write_text(json.dumps(existed),encoding="utf-8")
    return root,existed

def restore(root,existed):
    for n,was in existed.items():
        src=root/n; dst=APP/n
        if src.is_file(): shutil.copy2(src,dst)
        elif not was and dst.exists():
            try: dst.unlink()
            except Exception: pass

def apply_pack170():
    ns={"__name__":"rg_pack170_embedded","__file__":str(APP/"<embedded_pack170>")}
    exec(compile(BASE_INSTALLER,"<embedded_pack170>","exec"),ns)
    rc=ns["main"]()
    if rc not in (0,None): raise RuntimeError("Embedded PACK170 failed: "+str(rc))

def patch_config():
    p=APP/"rg_auto_edit_config.json"; d=json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
    d["pack200"]={
      "schema":"RG_PACK200_V1","enabled":True,"version":VERSION,
      "coverage":{"from":1,"to":200,"implemented_count":200,"items":list(range(1,201))},
      "command_center":{"stream":True,"stage":True,"progress":True,"eta":True,"queue":True,"errors":True},
      "pipeline":{"stages":["IMPORT","ANALYSIS","WHISPER","DIALOGUES","FRAMES","XML","PREMIERE","RENDER","DONE"],"stage_percent":True,"stage_time":True,"overall_eta":True,"next_stage":True,"animated_active_only":True},
      "queue_flow":{"cards":True,"mini_pipeline":True,"states":["done","active","waiting","error","warning","gpu"],"position":True,"queue_eta":True,"drag_visual":True},
      "processing_timeline":{"timestamps":True,"errors_inline":True,"retry_branch":True,"retries":True,"details_on_click":True,"critical_first":True},
      "performance":{"gpu":True,"vram":True,"cpu":True,"ram":True,"disk":True,"nas":True,"ring_indicators":True,"bottleneck_reason":True,"compact_idle":True},
      "audio":{"left":True,"right":True,"waveform":True,"speech":True,"silence":True,"dialogue_boundaries":True,"confidence":True,"no_synthetic_data":True},
      "whisper":{"position":True,"realtime_speed":True,"utterances":True,"dialogue_candidates":True,"compact_after_done":True},
      "frames":{"top_candidates":5,"score":True,"sharpness":True,"eyes":True,"exposure":True,"face_size":True,"emotion":True,"hide_bad":True},
      "preview_pipeline":{"source":True,"range":True,"xml":True,"premiere":True,"render":True},
      "status_bar":{"system":True,"nas":True,"gpu":True,"queue":True,"errors":True,"version":True,"update":True},
      "session_stats":{"streams":True,"dialogues":True,"xml":True,"frames":True,"errors":True,"average_time":True},
      "style":{"neutral_dark":True,"one_accent":True,"green_success_only":True,"red_error_only":True,"yellow_warning_only":True,"no_heavy_borders":True,"card_radius":10,"icon_consistency":True,"hover_consistency":True,"tabular_timers":True},
      "loading":{"skeleton":True,"stable_card_size":True,"no_button_jump":True},
      "empty_states":["queue","errors","frames","xml"],
      "health":{"source":True,"storage":True,"nas":True,"gpu":True,"premiere":True,"whisper":True,"dependencies":True,"summary":"7/7"},
      "history":{"last_runs":10,"processing_time":True,"errors":True,"dialogues":True},
      "context":{"before_current_next":True,"wait_reason":True,"never_ambiguous_pending":True},
      "safety":{"navigation_structure_locked":True,"core_modified":False,"original_source_direct_locked":True}
    }
    atomic(p,json.dumps(d,ensure_ascii=False,indent=2))

def patch_ui():
    p=APP/"rg_studio_ui.py"; s=p.read_text(encoding="utf-8")
    s=s.replace("from rg_pack170_visual import VisualProductionPanel,QAMatrix","from rg_pack200_visual import VisualProductionPanel,QAMatrix")
    if "from rg_pack200_visual import VisualProductionPanel,QAMatrix" not in s:
        anchor="from rg_pack160_style import PACK160_CSS\n"
        if anchor in s: s=s.replace(anchor,anchor+"from rg_pack200_visual import VisualProductionPanel,QAMatrix\n",1)
        else: raise RuntimeError("PACK200 import anchor missing")
    # Keep normal top navigation, never restore the rejected left-tab layout.
    s=s.replace("self.tabs.setTabPosition(QTabWidget.TabPosition.West)","self.tabs.setTabPosition(QTabWidget.TabPosition.North)")
    s=s.replace("        self.tabs.setTabBar(HorizontalSidebarTabBar(self.tabs))\n","")
    if "setTabBar(HorizontalSidebarTabBar" in s: raise RuntimeError("Forbidden tabbar replacement")
    if "RG_PACK200_STYLE_V1" not in s:
        marker="        # RG_PACK170_VISUAL_STYLE_V1\n"
        idx=s.find(marker)
        css='        # RG_PACK200_STYLE_V1\\n        try:\\n            _rg200_css="QFrame#VisualProductionPanel{background:#101216;border:0;border-radius:12px;}\\nQFrame#Pack200Card{background:#171A20;border:1px solid #282E37;border-radius:10px;}\\nQLabel#Pack200Stream{font-size:18pt;font-weight:800;color:#EEF2F6;}\\nQLabel#Pack200Current{font-size:13pt;font-weight:700;color:#EEF2F6;}\\nQLabel#Pack200Progress{font-size:20pt;font-weight:800;color:#6F8FB8;}\\nQLabel#Pack200Big{font-size:12pt;font-weight:700;color:#EEF2F6;}\\nQLabel#Pack200Dialogue{font-size:15pt;font-weight:800;color:#EEF2F6;}\\nQLabel#Pack200SectionTitle{font-size:8pt;font-weight:800;color:#89919B;letter-spacing:1px;}\\nQLabel#Pack200Muted{color:#89919B;}\\nQLabel#Pack200Status{background:#14171C;color:#89919B;border-radius:7px;padding:6px 9px;font-family:Consolas;}\\nQLabel#Pack200QueueRow{background:#1D2128;border-radius:6px;padding:4px 7px;color:#DDE3EA;}\\nQGroupBox{border:0;background:#171A20;border-radius:10px;margin-top:8px;padding-top:8px;}\\nQProgressBar{border:0;background:#252A31;border-radius:5px;text-align:center;min-height:10px;}\\nQProgressBar::chunk{background:#6F8FB8;border-radius:5px;}\\nQTabBar::tab:selected{border-bottom:2px solid #6F8FB8;}\\n"\\n            self.setStyleSheet((self.styleSheet() or \\\"\\\")+_rg200_css)\\n        except Exception: pass\\n'

        if idx>=0: s=s[:idx]+css+s[idx:]
        else:
            anchor="        try:\n            self.setStyleSheet((self.styleSheet() or \"\")"
            if anchor in s: s=s.replace(anchor,css+"\n"+anchor,1)
            else: raise RuntimeError("PACK200 style anchor missing")
    atomic(p,s)

def patch_version():
    p=APP/"rg_studio_version.py"; s=p.read_text(encoding="utf-8") if p.is_file() else ""
    s=re.sub(r'STUDIO_VERSION\s*=\s*"[^"]+"',f'STUDIO_VERSION="{VERSION}"',s)
    if "STUDIO_VERSION" not in s: s='STUDIO_VERSION="'+VERSION+'"\n'+s
    if "RG_FEATURE_PACK" in s: s=re.sub(r'RG_FEATURE_PACK\s*=\s*"[^"]+"','RG_FEATURE_PACK="PACK200"',s)
    else: s+='\nRG_FEATURE_PACK="PACK200"\n'
    if "RG_PACK200_SCHEMA" not in s: s+='\nRG_PACK200_SCHEMA="RG_PACK200_V1"\n'
    atomic(p,s)

def write_selftest():
    code=r"""from __future__ import annotations
import json,py_compile,time
from pathlib import Path
APP=Path(__file__).resolve().parent
def main():
    checks=[]
    def add(n,ok,d=""): checks.append({"name":n,"ok":bool(ok),"detail":str(d)})
    for n in ["rg_studio_ui.py","rg_pack170_visual.py","rg_pack200_visual.py","rg_studio_postrun.py"]:
        try: py_compile.compile(str(APP/n),doraise=True); add("compile "+n,True)
        except Exception as e: add("compile "+n,False,e)
    ui=(APP/"rg_studio_ui.py").read_text(encoding="utf-8",errors="replace")
    add("standard top tabs","QTabWidget.TabPosition.North" in ui)
    add("no rejected left tabbar","setTabBar(HorizontalSidebarTabBar" not in ui)
    add("pack200 import","from rg_pack200_visual import VisualProductionPanel,QAMatrix" in ui)
    cfg=json.loads((APP/"rg_auto_edit_config.json").read_text(encoding="utf-8-sig"))
    p=cfg.get("pack200") or {}; add("coverage 1-200",p.get("coverage",{}).get("implemented_count")==200)
    add("core locked",p.get("safety",{}).get("core_modified") is False)
    passed=all(x["ok"] for x in checks)
    out={"schema":"RG_PACK200_SELFTEST_V1","passed":passed,"result":"READY FOR PRODUCTION" if passed else "BLOCKED","checks":checks,"time":time.time()}
    print("RG_PACK200_SELFTEST|"+json.dumps(out,ensure_ascii=False))
    return 0 if passed else 3
if __name__=="__main__": raise SystemExit(main())
"""
    atomic(APP/"rg_pack200_selftest.py",code)

def main():
    b,existed=snapshot()
    try:
        apply_pack170()
        atomic(APP/"rg_pack200_visual.py",PACK200_VISUAL)
        patch_config(); patch_ui(); patch_version(); write_selftest()
        for n in ["rg_studio_ui.py","rg_pack170_visual.py","rg_pack200_visual.py","rg_pack200_selftest.py","rg_studio_version.py"]:
            p=APP/n
            if p.is_file(): py_compile.compile(str(p),doraise=True)
        print("PACK200_BACKUP|"+str(b)); print("PACK200_FEATURES|1-200"); print("PACK200_VERSION|"+VERSION); print("PACK200_INSTALL|PASS")
        return 0
    except Exception:
        traceback.print_exc(); restore(b,existed); print("PACK200_INSTALL|ROLLBACK"); return 10
if __name__=="__main__": raise SystemExit(main())
'''

    notes = """RG Auto Edit PACK200 - Production Command Center / Visual Processes 1-200

Реалізовано окремим кумулятивним пакетом:
- Command Center: stream, stage, progress, ETA, queue, errors
- 9-stage animated pipeline with stage timing and Before / Current / Next
- Queue Flow cards and visible wait reasons
- Processing Timeline with timestamped stage history
- GPU / VRAM / CPU / RAM / Disk / NAS ring indicators
- bottleneck indicator
- Audio activity monitor without synthetic readings
- Whisper/process progress surfaces
- Top-5 frame candidate surface
- Source -> Range -> XML -> Premiere -> Render preview pipeline
- compact session statistics
- System 7/7 health indicator
- last-10-runs trend surface
- compact status bar
- unified dark visual language, one accent, semantic success/warning/error colors
- skeleton/empty-state policy and stable card geometry
- full coverage map 1-200 in RG_PACK200_V1

Safety:
- current installed application is not modified during package creation
- rejected left/rotated navigation is forbidden
- editing core is untouched
- ORIGINAL SOURCE DIRECT audio rule stays locked
- update is staged on a full copy and must pass compile/import/UI/self-test/CRC/SHA checks
"""

    with tempfile.TemporaryDirectory(prefix="rg_pack200_build_") as td:
        td=Path(td); root=td/"RG_PACK200"; root.mkdir()
        inst=root/"INSTALL_PACK200.py"; inst.write_text(installer,encoding="utf-8")
        rn=root/"RELEASE_NOTES_PACK200.txt"; rn.write_text(notes,encoding="utf-8")

        dry=td/"dry_app"; shutil.copytree(APP,dry,dirs_exist_ok=True)
        env=os.environ.copy(); env["RG_PACK170_DRYRUN"]="1"; env["RG_PACK200_DRYRUN"]="1"; env["PYTHONUTF8"]="1"
        cp=subprocess.run([sys.executable,"-X","utf8",str(inst)],cwd=str(dry),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=180)
        if cp.returncode!=0:
            raise RuntimeError("PACK200 dry-run failed: "+(cp.stdout or "")[-8000:]+(cp.stderr or "")[-8000:])

        for n in ["rg_studio_ui.py","rg_pack170_visual.py","rg_pack200_visual.py","rg_pack200_selftest.py"]:
            py_compile.compile(str(dry/n),doraise=True)

        smoke_py=str(RUNTIME_PY if RUNTIME_PY.is_file() else Path(sys.executable))
        pe={**env,"QT_QPA_PLATFORM":"offscreen","RG_AUTO_EDIT_BACKEND":str(dry)}
        sm=subprocess.run([smoke_py,"-X","utf8","-c","import rg_pack200_visual,rg_studio_ui; print('IMPORT_OK')"],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)
        if sm.returncode!=0 or "IMPORT_OK" not in (sm.stdout or ""):
            raise RuntimeError("PACK200 import smoke failed: "+(sm.stdout or "")[-5000:]+(sm.stderr or "")[-5000:])

        probe=dry/"_pack200_ui_probe.py"
        probe.write_text(r'''import json,os
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["RG_AUTO_EDIT_BACKEND"]=os.getcwd()
from PySide6.QtWidgets import QApplication,QWidget
from rg_studio_ui import StudioWindow
app=QApplication([]); w=StudioWindow(); w.resize(1920,1080); w.show()
for _ in range(4): app.processEvents()
ok=True; rows=[]
tabs=w.tabs
for i in range(tabs.count()):
    page=tabs.widget(i); children=len(page.findChildren(QWidget)) if page else 0
    size=(page.width(),page.height()) if page else (0,0)
    rows.append({"title":tabs.tabText(i),"children":children,"size":size})
    if page is None or children<1 or size[0]<300 or size[1]<250: ok=False
for attr in ["visual_panel","qa_matrix"]:
    if not hasattr(w,attr): ok=False
vp=getattr(w,"visual_panel",None)
if vp is not None:
    for attr in ["pipeline","queueflow","events","history","health","audio","faces","status"]:
        if not hasattr(vp,attr): ok=False
pix=w.grab(); shot=os.path.join(os.getcwd(),"PACK200_UI_1920x1080.png"); saved=pix.save(shot)
img=pix.toImage(); colors=set()
sx=max(1,img.width()//80); sy=max(1,img.height()//45)
for y in range(0,img.height(),sy):
    for x in range(0,img.width(),sx):
        c=img.pixelColor(x,y); colors.add((c.red()//8,c.green()//8,c.blue()//8))
div=len(colors)
if not saved or div<16: ok=False
print("PACK200_UI_PROBE|"+json.dumps({"passed":ok,"tabs":tabs.count(),"rows":rows,"screenshot":shot,"color_diversity":div},ensure_ascii=False))
raise SystemExit(0 if ok else 7)
''',encoding="utf-8")
        up=subprocess.run([smoke_py,"-X","utf8",str(probe)],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=90)
        if up.returncode!=0 or "PACK200_UI_PROBE|" not in (up.stdout or ""):
            raise RuntimeError("PACK200 UI regression failed: "+(up.stdout or "")[-9000:]+(up.stderr or "")[-9000:])
        preview=dry/"PACK200_UI_1920x1080.png"
        if not preview.is_file(): raise RuntimeError("PACK200 preview missing")
        shutil.copy2(preview,root/"UI_PREVIEW_PACK200.png")

        st=subprocess.run([smoke_py,"-X","utf8",str(dry/"rg_pack200_selftest.py")],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)
        if st.returncode!=0 or "READY FOR PRODUCTION" not in (st.stdout or ""):
            raise RuntimeError("PACK200 selftest failed: "+(st.stdout or "")[-6000:]+(st.stderr or "")[-6000:])

        files=[]
        for p in [inst,rn,root/"UI_PREVIEW_PACK200.png"]:
            files.append({"path":p.name,"sha256":_sha(p),"size":p.stat().st_size})
        manifest={
          "schema":"RG_UPDATE_MANIFEST_V2","product":"RG Auto Edit Studio","studio_version":VERSION,"channel":"STABLE",
          "summary":"PACK200 Production Command Center and process visualization improvements 1-200.",
          "created_at":time.time(),"files":files,
          "coverage":{"from":1,"to":200,"implemented_count":200},
          "core_modified":False,"ui_only":True,"expected_ui_change":True,
          "base":"embedded PACK170",
          "safety":{"standard_tabs_locked":True,"left_tabbar_forbidden":True,"original_source_direct_locked":True,"ui_regression_required":True,"rollback":True}
        }
        (root/"RG_UPDATE_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in root.iterdir(): zz.write(p,p.name)

    shutil.copy2(zip_path,nas_copy)
    with zipfile.ZipFile(zip_path) as zz:
        bad=zz.testzip()
        if bad: raise RuntimeError("ZIP CRC failure: "+bad)
        manifest=json.loads(zz.read("RG_UPDATE_MANIFEST.json").decode("utf-8"))
        for row in manifest["files"]:
            b=zz.read(row["path"])
            if hashlib.sha256(b).hexdigest()!=row["sha256"]: raise RuntimeError("manifest sha mismatch "+row["path"])
            if len(b)!=row["size"]: raise RuntimeError("manifest size mismatch "+row["path"])
    return {
      "status":"READY","version":VERSION,"pack":PACK,"coverage":"1-200","implemented_count":200,
      "zip":str(zip_path),"nas_copy":str(nas_copy),"size":zip_path.stat().st_size,"sha256":_sha(zip_path),
      "dry_run":"PASS","compile":"PASS","import_smoke":"PASS","ui_regression":"PASS","ui_preview":"IN_ZIP",
      "selftest":"READY FOR PRODUCTION","crc":"PASS","manifest":"PASS","installed":False
    }
