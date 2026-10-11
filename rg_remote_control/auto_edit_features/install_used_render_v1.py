# RG Auto Edit FFmpeg progress + usage + compact notification, safe patcher.
from __future__ import annotations
import ast
import datetime
import os
import py_compile
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
HERE = Path(__file__).resolve().parent
MARKER = "RG_USAGE_PROGRESS_V1"

def replace_one(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)

def patch_ff(src):
    old = "'-progress',str(JOB/'RG_FFMPEG_PROGRESS.txt'),'-nostats',str(tmp)]"
    new = "'-progress','pipe:1','-stats_period','1','-nostats',str(tmp)]"
    src = replace_one(src,old,new,"ffmpeg progress pipe")
    old = """    with (JOB/'RG_FFMPEG_RENDER.log').open('w',encoding='utf-8') as log:
        proc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    if proc.returncode:fail('ffmpeg rendering failed; inspect '+str(JOB/'RG_FFMPEG_RENDER.log'))"""
    new = """    # RG_USAGE_PROGRESS_V1: real FFmpeg encoding-time telemetry, not file-size estimates.
    started=time.monotonic()
    progress={}
    with (JOB/'RG_FFMPEG_RENDER.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              text=True,errors='replace',bufsize=1)
        for raw_line in proc.stdout:
            line=raw_line.strip()
            log.write(raw_line)
            if '=' not in line:
                continue
            name,value=line.split('=',1)
            if name in ('out_time_us','out_time_ms','out_time','speed','fps','total_size','progress'):
                progress[name]=value
            if name == 'progress':
                try:
                    micros=progress.get('out_time_us') or progress.get('out_time_ms') or '0'
                    current=max(0.0,min(expected,float(micros)/1000000.0))
                    if not current and progress.get('out_time'):
                        h,m,s=progress['out_time'].split(':')
                        current=min(expected,int(h)*3600+int(m)*60+float(s))
                except (ValueError,TypeError):
                    current=0.0
                speed_text=progress.get('speed','N/A')
                try:speed_num=float(speed_text.rstrip('x'))
                except (ValueError,TypeError):speed_num=0.0
                eta_sec=(expected-current)/speed_num if speed_num>0.01 else None
                boundary=0.0
                current_idx=len(sources)-1
                for idx,(_,duration,_) in enumerate(sources):
                    boundary+=duration
                    if current<boundary:
                        current_idx=idx
                        break
                item={'percent':round(100.0*current/expected,2),
                      'processed_sec':round(current,1),'total_sec':round(expected,1),
                      'elapsed_sec':round(time.monotonic()-started,1),
                      'eta_sec':round(eta_sec) if eta_sec is not None else None,
                      'speed':speed_text,'fps':progress.get('fps',''),
                      'current_index':current_idx+1,'total_items':len(sources),
                      'current_name':sources[current_idx][0].name,
                      'size_bytes':int(progress.get('total_size') or 0)}
                print('RGFFPROGRESS|'+json.dumps(item,ensure_ascii=False),flush=True)
                progress={}
        rc=proc.wait()
    if rc:fail('ffmpeg rendering failed; inspect '+str(JOB/'RG_FFMPEG_RENDER.log'))"""
    return replace_one(src,old,new,"ffmpeg telemetry")

def patch_comp(src):
    old = """                elif line.startswith("RENDER_STARTED:"):emit(65,"FFMPEG",line)
                elif line.startswith("FINAL_MP4_PASS:"):emit(99,"FFMPEG",line)"""
    new = """                elif line.startswith("RENDER_STARTED:"):emit(65,"FFMPEG",line)
                elif line.startswith("RGFFPROGRESS|"):
                    try:
                        d=json.loads(line.split("|",1)[1])
                        pc=65.0+32.0*float(d["percent"])/100.0
                        def mmss(value):
                            if value is None:return "—"
                            value=max(0,int(float(value)));return f"{value//3600:02d}:{value//60%60:02d}:{value%60:02d}"
                        msg=(f"{mmss(d['processed_sec'])} / {mmss(d['total_sec'])} • "
                             f"залишилось ~{mmss(d.get('eta_sec'))} • {d['speed']} • "
                             f"{d['fps']} FPS • {d['current_index']}/{d['total_items']} "
                             f"{d['current_name']} • {d['size_bytes']/1048576:.0f} MB")
                        emit(pc,"RENDER",msg)
                    except (ValueError,TypeError,KeyError,IndexError) as exc:
                        print("RG_FFMPEG_METRIC_PARSE_WARNING|"+str(exc),flush=True)
                elif line.startswith("FINAL_MP4_PASS:"):emit(99,"FFMPEG",line)"""
    src=replace_one(src,old,new,"parent progress parsing")
    old="""        result["retirement"]={"retired":[],"errors":[],"note":"Sources intentionally retained"}
        result["retired_count"]=0
        result["retirement_errors"]=0"""
    new="""        # RG_USAGE_PROGRESS_V1: register only after ffprobe-verified MP4 is complete.
        from rg_used_dialogues import record_success
        result["used_marked_count"]=record_success(clips,output,job)
        result["retirement"]={"retired":[],"errors":[],"note":"Sources intentionally retained"}
        result["retired_count"]=0
        result["retirement_errors"]=0"""
    src=replace_one(src,old,new,"register on render success")
    # Usage is tracked in separate registry; do not rename files.
    old="""    used=_load_used_registry()
    files = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not is_retired_dialogue(p) and str(p.resolve()).lower() not in used],
                   key=lambda p: natural_key(p.name))"""
    new="""    from rg_used_dialogues import statuses
    files = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS],
                   key=lambda p: natural_key(p.name))
    flags=statuses(files)"""
    src=replace_one(src,old,new,"show used in library")
    old="""rows.append(dict(dialogue=p.stem, name=p.name, path=str(p), duration_sec=round(i["duration_sec"], 3),
                             fps=round(i["fps"], 6), size_bytes=p.stat().st_size))"""
    new="""rows.append(dict(dialogue=p.stem, name=p.name, path=str(p), duration_sec=round(i["duration_sec"], 3),
                             fps=round(i["fps"], 6), size_bytes=p.stat().st_size,
                             **flags[str(p)]))"""
    src=replace_one(src,old,new,"scan usage metadata")
    old="""rows.append(dict(dialogue=p.stem, name=p.name, path=str(p), duration_sec=None, error=str(e)))"""
    new="""rows.append(dict(dialogue=p.stem, name=p.name, path=str(p), duration_sec=None, error=str(e), **flags[str(p)]))"""
    return replace_one(src,old,new,"scan broken file flags")

def patch_ui(src):
    old='gl.addWidget(self.thumb_final_stage,3,3)'
    new='''gl.addWidget(self.thumb_final_stage,3,3)
        # RG_USAGE_PROGRESS_V1
        self.thumb_final_details=QLabel("Очікує запуску • FFmpeg");self.thumb_final_details.setWordWrap(True)
        self.thumb_final_details.setProperty("muted","true");gl.addWidget(self.thumb_final_details,4,0,1,4)'''
    src=replace_one(src,old,new,"ui render details")
    old='''        self.thumb_table=QTableWidget(0,4);self.thumb_table.setHorizontalHeaderLabels(["✓","ДІАЛОГ","ТРИВАЛІСТЬ","ФАЙЛ"])'''
    new='''        used_controls=QHBoxLayout()
        used_controls.addWidget(QLabel("Показати"))
        self.thumb_used_filter=QComboBox()
        self.thumb_used_filter.addItem("Вільні","free")
        self.thumb_used_filter.addItem("Усі","all")
        self.thumb_used_filter.addItem("Використані","used")
        self.thumb_used_filter.currentIndexChanged.connect(lambda _:self.thumbnail_refresh_dialogues())
        used_controls.addWidget(self.thumb_used_filter)
        self.thumb_used_counter=QLabel("");used_controls.addWidget(self.thumb_used_counter)
        used_controls.addStretch()
        used_button=_button("ПОЗНАЧИТИ БУЛО")
        used_button.clicked.connect(lambda:self._rg_usage_manual(True))
        used_controls.addWidget(used_button)
        free_button=_button("ПОВЕРНУТИ У ВІЛЬНІ")
        free_button.clicked.connect(lambda:self._rg_usage_manual(False))
        used_controls.addWidget(free_button)
        v.addLayout(used_controls)
        self.thumb_table=QTableWidget(0,5);self.thumb_table.setHorizontalHeaderLabels(["✓","ДІАЛОГ","ТРИВАЛІСТЬ","ФАЙЛ","СТАН"])'''
    src=replace_one(src,old,new,"ui filters and controls")
    old='''self.thumb_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)'''
    new='''self.thumb_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.thumb_table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeToContents)'''
    src=replace_one(src,old,new,"ui column sizing")
    src=replace_one(src,'self.thumb_table.setSelectionMode(QTableWidget.SingleSelection)',
                    'self.thumb_table.setSelectionMode(QTableWidget.ExtendedSelection)',"ui multi select")
    old='''        self._thumb_source_meta={str(row.get('path','')):row for row in rows}'''
    new='''        self._thumb_source_meta={str(row.get('path','')):row for row in rows}
        free_count=sum(not row.get("used") for row in rows)
        used_count=len(rows)-free_count
        if hasattr(self,"thumb_used_counter"):
            self.thumb_used_counter.setText(f"Вільні: {free_count} • БУЛО: {used_count}")
        filt=self.thumb_used_filter.currentData() if hasattr(self,"thumb_used_filter") else "all"
        if filt=="free":rows=[r for r in rows if not r.get("used")]
        elif filt=="used":rows=[r for r in rows if r.get("used")]'''
    src=replace_one(src,old,new,"filter rows")
    old='''self.thumb_table.setItem(r,3,fi)'''
    new='''self.thumb_table.setItem(r,3,fi)
                used=bool(row.get("used"))
                label="✓ БУЛО" if used else "ВІЛЬНИЙ"
                note=str(row.get("last_output") or "")
                count=int(row.get("count") or 0)
                if count:label+=f" ({count})"
                si=QTableWidgetItem(label)
                si.setToolTip(("Останнє відео: "+note) if note else ("Відмічено вручну" if used else "Не використаний"))
                self.thumb_table.setItem(r,4,si)'''
    src=replace_one(src,old,new,"used status column")
    old='''    def _thumbnail_checked_paths(self):'''
    new='''    def _rg_usage_manual(self, used):
        if getattr(self,"_thumbnail_final_active",False):
            QMessageBox.information(self,"Діалоги","Зачекай до завершення рендера.");return
        rows=sorted(set(i.row() for i in self.thumb_table.selectionModel().selectedRows()))
        if not rows:
            QMessageBox.information(self,"Діалоги","Виділи рядки файлів у таблиці (Ctrl/Shift для кількох).");return
        paths=[]
        for row in rows:
            item=self.thumb_table.item(row,3)
            if item:paths.append(str(item.data(Qt.UserRole) or item.text()))
        if not paths:return
        try:
            from rg_used_dialogues import manual_mark
            count=manual_mark(paths,bool(used))
            self.thumbnail_refresh_dialogues()
            self.thumb_status.setText(f"Оновлено статус {count} діалогів • файли не перейменовувалися")
        except Exception as exc:
            QMessageBox.warning(self,"Діалоги",f"Не вдалося зберегти позначки:\\\\n{exc}")

    def _thumbnail_checked_paths(self):'''
    src=replace_one(src,old,new,"manual status method")
    old='''        job=self._thumbnail_ensure_job()
        work=APP_DIR/"FINAL_COMPILATIONS"/job;work.mkdir(parents=True,exist_ok=True)'''
    new='''        from rg_used_dialogues import statuses
        flags=statuses(selected)
        old=[Path(p).name for p in selected if flags[p]["used"]]
        if old:
            prompt="Ці діалоги вже використовувались:\\\\n"+", ".join(old[:12])+"\\\\n\\\\nЗібрати повторно?"
            if QMessageBox.question(self,"Повторне використання",prompt,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
                return
        job=self._thumbnail_ensure_job()
        work=APP_DIR/"FINAL_COMPILATIONS"/job;work.mkdir(parents=True,exist_ok=True)'''
    src=replace_one(src,old,new,"reused confirmation")
    src=replace_one(src,'self.thumb_final_render_btn.setText("PREMIERE РЕНДЕР...")',
                    'self.thumb_final_render_btn.setText("FFMPEG • РЕНДЕР...")',"render button")
    src=replace_one(src,'Запускаю Adobe Premiere…','Запускаю FFmpeg…',"render status text")
    old='''        if hasattr(self,"thumb_final_stage"):self.thumb_final_stage.setText(f"{stage} • {msg}")

    def thumbnail_final_render(self):'''
    new='''        if hasattr(self,"thumb_final_stage"):self.thumb_final_stage.setText(f"{stage} • {msg}" if stage!="RENDER" else "FFmpeg • кодування")
        if hasattr(self,"thumb_final_details"):self.thumb_final_details.setText(msg)

    def thumbnail_final_render(self):'''
    src=replace_one(src,old,new,"ui real telemetry details")
    old='''            retired=int(result.get("retired_count") or 0);retire_err=int(result.get("retirement_errors") or 0)
            used_msg=f" • використано/БЫЛО: {retired}"
            if retire_err:used_msg+=f" • помилок перейменування: {retire_err}"
            self.thumb_status.setText(f"ФІНАЛЬНЕ ВІДЕО ГОТОВО ✓ • діалогів: {result.get('dialogue_count',0)} • перебивок ГРАНАТА: {result.get('grenade_count',0)} • Gain -9 dB{used_msg}\\n{result.get('render_output','')}{golden_msg}")
            QMessageBox.information(self,"Фінальна збірка",f"Рендер завершено.\\n\\n{result.get('render_output','')}\\n\\nВикористані діалоги позначено БЫЛО: {retired}{golden_msg}")'''
    new='''            used_count=int(result.get("used_marked_count") or 0)
            output_path=Path(str(result.get("render_output") or ""))
            self.thumb_status.setText(f"ФІНАЛЬНЕ ВІДЕО ГОТОВО ✓ • діалогів: {result.get('dialogue_count',0)} • позначено БУЛО: {used_count} • перебивок: {result.get('grenade_count',0)}\\n{output_path}")
            if hasattr(self,"thumb_final_details"):self.thumb_final_details.setText("MP4 перевірено • звук є • діалоги позначено БУЛО")
            # RG_USAGE_PROGRESS_V1: compact completion dialog
            alert=QMessageBox(self)
            alert.setIcon(QMessageBox.Information)
            alert.setWindowTitle("Фінальне відео готове")
            alert.setText("✓ ФІНАЛЬНЕ ВІДЕО ГОТОВЕ")
            duration=int(round(float(result.get("duration_sec") or 0)))
            info=(f"{output_path.name}\\n"
                  f"Тривалість: {duration//60:02d}:{duration%60:02d}  •  "
                  f"Діалогів: {result.get('dialogue_count',0)}  •  БУЛО: {used_count}")
            alert.setInformativeText(info)
            alert.setDetailedText(str(output_path))
            open_btn=alert.addButton("ВІДКРИТИ ПАПКУ",QMessageBox.ActionRole)
            alert.addButton("ГОТОВО",QMessageBox.AcceptRole)
            alert.exec()
            if alert.clickedButton() is open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_path.parent)))'''
    src=replace_one(src,old,new,"compact success dialog")
    src=replace_one(src,'"Premiere-рендер не завершився.\\n\\n"+tail[-1800:]','"FFmpeg-рендер не завершився. Переглянь деталі помилки.\\n\\n"+tail[-500:]',"error dialog old text")
    return src

def main():
    apply = "--apply" in sys.argv
    srcs = {}
    targets={"rg_final_ffmpeg.py":patch_ff,"rg_final_compilation.py":patch_comp,"rg_studio_ui.py":patch_ui}
    for name,func in targets.items():
        p=APP/name
        original=p.read_text(encoding="utf-8-sig")
        if MARKER in original:
            if "--apply" in sys.argv:
                raise RuntimeError(name + " already contains patch marker. Stop and audit; no double patch.")
            print(name+": ALREADY_PATCHED")
            continue
        patched=func(original)
        ast.parse(patched,filename=name)
        srcs[name]=(p,original,patched)
    registry_source=HERE/"rg_used_dialogues.py"
    ast.parse(registry_source.read_text(encoding="utf-8"),filename="rg_used_dialogues.py")
    print("PRECHECK: PASS; FILES:",",".join(srcs))
    print("NO_VIDEO_PROCESSING: TRUE")
    if not apply:
        print("NO_CHANGES: PASS")
        return
    stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup=DATA/"release_backups"/("used_render_"+stamp)
    backup.mkdir(parents=True,exist_ok=False)
    for name,(p,original,patched) in srcs.items():
        shutil.copy2(p,backup/name)
    registry_target=APP/"rg_used_dialogues.py"
    if registry_target.exists():
        shutil.copy2(registry_target,backup/"rg_used_dialogues.py")
    pending={}
    for name,(p,original,patched) in srcs.items():
        pending[p]=patched
    pending[registry_target]=registry_source.read_text(encoding="utf-8")
    try:
        for p,source in pending.items():
            tmp=p.with_name(p.name+".used_render.tmp")
            tmp.write_text(source,encoding="utf-8")
            py_compile.compile(str(tmp),doraise=True)
            os.replace(tmp,p)
        for p in pending:
            py_compile.compile(str(p),doraise=True)
    except Exception:
        for name in srcs:
            shutil.copy2(backup/name,APP/name)
        if (backup/"rg_used_dialogues.py").is_file():
            shutil.copy2(backup/"rg_used_dialogues.py",registry_target)
        elif registry_target.is_file():
            registry_target.unlink()
        raise
    print("RG_USAGE_PROGRESS_V1_APPLIED: PASS")
    print("BACKUP:",backup)
    print("NO_MP4_RENAMED: TRUE")
    print("RESTART_STUDIO_REQUIRED: TRUE")

if __name__=="__main__":
    main()
