from __future__ import annotations
import hashlib,json,os,re,shutil,subprocess,sys,tempfile,time,zipfile,py_compile
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNTIME_PY=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
VERSION="0.20.7.2"
PACK="PACK312"
NAME=f"RG_AUTO_EDIT_STUDIO_UPDATE_{VERSION}_{PACK}_PREVIEW_DURATION_PLAYER.zip"

def _sha(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def build_auto_edit_pack312_update()->dict:
    if os.name!="nt":
        raise RuntimeError("Windows only")
    if not APP.is_dir():
        raise RuntimeError("RG Auto Edit app not found")

    downloads=Path.home()/"Downloads";downloads.mkdir(parents=True,exist_ok=True)
    packages=DATA/"PACKAGES";packages.mkdir(parents=True,exist_ok=True)
    zip_path=downloads/NAME
    nas_copy=packages/NAME

    helper=r'''from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem,QHeaderView

class DurationItem(QTableWidgetItem):
    def __lt__(self,other):
        try:
            a=self.data(Qt.ItemDataRole.UserRole)
            b=other.data(Qt.ItemDataRole.UserRole)
            if a is not None and b is not None:
                return float(a)<float(b)
        except Exception:
            pass
        return super().__lt__(other)

def duration_seconds(text):
    try:
        parts=[int(x) for x in str(text or "").strip().split(":")]
        if len(parts)==3:return parts[0]*3600+parts[1]*60+parts[2]
        if len(parts)==2:return parts[0]*60+parts[1]
        if len(parts)==1:return parts[0]
    except Exception:
        pass
    return 0

def _convert_duration_cells(table):
    for row in range(table.rowCount()):
        old=table.item(row,2)
        if old is None:
            continue
        if isinstance(old,DurationItem):
            old.setData(Qt.ItemDataRole.UserRole,duration_seconds(old.text()))
            continue
        item=DurationItem(old.text())
        item.setData(Qt.ItemDataRole.UserRole,duration_seconds(old.text()))
        item.setFlags(old.flags())
        item.setTextAlignment(old.textAlignment())
        tooltip=old.data(Qt.ItemDataRole.ToolTipRole)
        if tooltip is not None:item.setData(Qt.ItemDataRole.ToolTipRole,tooltip)
        table.setItem(row,2,item)

def sort_duration(host,table):
    current_id=""
    try:
        row=table.currentRow()
        if row>=0 and table.item(row,1):
            current_id=table.item(row,1).text()
    except Exception:
        pass
    table.blockSignals(True)
    try:
        table.setSortingEnabled(False)
        _convert_duration_cells(table)
        order=getattr(host,"_thumb_duration_sort_order",Qt.SortOrder.DescendingOrder)
        table.setSortingEnabled(True)
        table.sortItems(2,order)
        table.setSortingEnabled(False)
        table.horizontalHeader().setSortIndicator(2,order)
        host._thumb_duration_sort_order=(Qt.SortOrder.AscendingOrder if order==Qt.SortOrder.DescendingOrder else Qt.SortOrder.DescendingOrder)
        if current_id:
            for row in range(table.rowCount()):
                it=table.item(row,1)
                if it and it.text()==current_id:
                    table.selectRow(row)
                    break
    finally:
        table.blockSignals(False)

def install_preview_table(host,table):
    # FILE stays internally because existing playback logic may read column 3.
    # It is hidden from the UI.
    table.setColumnHidden(3,True)
    hdr=table.horizontalHeader()
    hdr.setSectionsClickable(True)
    hdr.setSortIndicatorShown(True)
    hdr.setSortIndicator(2,Qt.SortOrder.DescendingOrder)
    hdr.setSectionResizeMode(0,QHeaderView.ResizeToContents)
    hdr.setSectionResizeMode(1,QHeaderView.Stretch)
    hdr.setSectionResizeMode(2,QHeaderView.ResizeToContents)
    table.setToolTip("Клік по «ТРИВАЛІСТЬ» - сортування за реальною тривалістю.")
    host._thumb_duration_sort_order=Qt.SortOrder.DescendingOrder
    hdr.sectionClicked.connect(lambda section: sort_duration(host,table) if int(section)==2 else None)
'''

    installer="from __future__ import annotations\nPACK312_HELPER="+repr(helper)+"\n"+r'''
import json,os,re,shutil,time,traceback,py_compile
from pathlib import Path

APP=Path.cwd()
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
VERSION="0.20.7.2"

def atomic(p,text):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".pack312.tmp")
    t.write_text(text,encoding="utf-8")
    os.replace(t,p)

def snapshot():
    root=DATA/"release_backups"/("PRE_PACK312_"+time.strftime("%Y%m%d_%H%M%S"))
    root.mkdir(parents=True,exist_ok=True)
    names=["rg_studio_ui.py","rg_auto_edit_config.json","rg_studio_version.py","rg_pack312_preview.py"]
    existed={}
    for n in names:
        p=APP/n;existed[n]=p.exists()
        if p.is_file():shutil.copy2(p,root/n)
    (root/"_existed.json").write_text(json.dumps(existed),encoding="utf-8")
    return root,existed

def restore(root,existed):
    for n,was in existed.items():
        src=root/n;dst=APP/n
        if src.is_file():shutil.copy2(src,dst)
        elif not was and dst.exists():
            try:dst.unlink()
            except Exception:pass

def patch_ui():
    p=APP/"rg_studio_ui.py"
    if not p.is_file():raise RuntimeError("rg_studio_ui.py not found in updater cwd: "+str(APP))
    s=p.read_text(encoding="utf-8")

    if "from rg_pack312_preview import install_preview_table" not in s:
        anchor="from rg_internal_browser import RGInternalBrowser\n"
        if anchor not in s:raise RuntimeError("preview import anchor missing")
        s=s.replace(anchor,anchor+"from rg_pack312_preview import install_preview_table\n",1)

    table_anchor='self.thumb_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)'
    if table_anchor not in s:raise RuntimeError("thumbnail table header anchor missing")
    if "RG_PACK312_PREVIEW_TABLE" not in s:
        s=s.replace(table_anchor,table_anchor+'\n        # RG_PACK312_PREVIEW_TABLE\n        install_preview_table(self,self.thumb_table)',1)

    if "media_row.addWidget(self.thumb_table,3)" not in s:
        raise RuntimeError("thumbnail table stretch anchor missing")
    s=s.replace("media_row.addWidget(self.thumb_table,3)","media_row.addWidget(self.thumb_table,2)",1)

    s,n=re.subn(r'media_row\.addWidget\(pg,\s*\d+\)',"media_row.addWidget(pg,3)",s,count=1)
    if n!=1:raise RuntimeError("preview player stretch anchor missing")

    s,n=re.subn(
        r'self\.thumb_video\.setMinimumHeight\(\d+\);self\.thumb_video\.setMaximumHeight\(\d+\)',
        "self.thumb_video.setMinimumHeight(250);self.thumb_video.setMaximumHeight(330)",
        s,count=1
    )
    if n!=1:raise RuntimeError("preview player height anchor missing")

    atomic(p,s)

def patch_config():
    p=APP/"rg_auto_edit_config.json"
    d=json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
    d["pack312"]={
      "schema":"RG_PACK312_PREVIEW_V1","enabled":True,"version":VERSION,
      "preview_dialogues":{
        "duration_sort":True,
        "duration_sort_numeric_seconds":True,
        "duration_sort_toggle":True,
        "file_column_visible":False,
        "file_column_kept_internal":True,
        "table_player_stretch":[2,3],
        "player_min_height":250,
        "player_max_height":330,
        "selection_preserved_during_sort":True
      },
      "safety":{"preview_only":True,"editing_core_untouched":True,"original_source_direct_locked":True}
    }
    atomic(p,json.dumps(d,ensure_ascii=False,indent=2))

def patch_version():
    p=APP/"rg_studio_version.py"
    s=p.read_text(encoding="utf-8") if p.is_file() else ""
    if re.search(r'STUDIO_VERSION\s*=\s*["\'][^"\']+["\']',s):
        s=re.sub(r'STUDIO_VERSION\s*=\s*["\'][^"\']+["\']','STUDIO_VERSION="'+VERSION+'"',s,count=1)
    else:
        s='STUDIO_VERSION="'+VERSION+'"\n'+s
    if re.search(r'RG_FEATURE_PACK\s*=\s*["\'][^"\']+["\']',s):
        s=re.sub(r'RG_FEATURE_PACK\s*=\s*["\'][^"\']+["\']','RG_FEATURE_PACK="PACK312"',s,count=1)
    else:
        s+='\nRG_FEATURE_PACK="PACK312"\n'
    atomic(p,s)

def main():
    root,existed=snapshot()
    try:
        atomic(APP/"rg_pack312_preview.py",PACK312_HELPER)
        patch_ui()
        patch_config()
        patch_version()
        for n in ["rg_studio_ui.py","rg_pack312_preview.py","rg_studio_version.py"]:
            py_compile.compile(str(APP/n),doraise=True)
        print("PACK312_TARGET|"+str(APP))
        print("PACK312_BACKUP|"+str(root))
        print("PACK312_INSTALL|PASS")
        return 0
    except Exception:
        traceback.print_exc()
        restore(root,existed)
        print("PACK312_INSTALL|ROLLBACK")
        return 10

if __name__=="__main__":
    raise SystemExit(main())
'''

    notes="""RG Auto Edit PACK312 - PREVIEW duration sorting + larger player

Точковий hotfix для поточної Studio 0.20.7.0.

Зміни:
- колонка ФАЙЛ прихована з інтерфейсу;
- шлях до файлу залишається у прихованій колонці для сумісності playback;
- клік по ТРИВАЛІСТЬ сортує числово за секундами;
- повторний клік перемикає напрямок;
- список/плеєр = 2/3 на користь плеєра;
- висота відео = 250-330 px;
- вибраний діалог зберігається при сортуванні;
- монтажне ядро та аудіо не змінюються.
"""

    with tempfile.TemporaryDirectory(prefix="rg_pack312_build_") as td:
        td=Path(td);root=td/"RG_PACK312";root.mkdir()
        inst=root/"INSTALL_PACK312.py";inst.write_text(installer,encoding="utf-8")
        rn=root/"RELEASE_NOTES_PACK312.txt";rn.write_text(notes,encoding="utf-8")

        # Test against an exact copy of the CURRENT live backend, without applying older packs.
        dry=td/"dry_app"
        shutil.copytree(APP,dry,dirs_exist_ok=True)
        env=os.environ.copy();env["PYTHONUTF8"]="1"
        cp=subprocess.run([sys.executable,"-X","utf8",str(inst)],cwd=str(dry),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=180)
        if cp.returncode!=0:
            raise RuntimeError("PACK312 install-on-current-copy failed: "+(cp.stdout or "")[-12000:]+(cp.stderr or "")[-12000:])

        for n in ["rg_studio_ui.py","rg_pack312_preview.py","rg_studio_version.py"]:
            py_compile.compile(str(dry/n),doraise=True)

        smoke_py=str(RUNTIME_PY if RUNTIME_PY.is_file() else Path(sys.executable))
        pe={**env,"QT_QPA_PLATFORM":"offscreen","RG_AUTO_EDIT_BACKEND":str(dry)}
        probe=dry/"_pack312_probe.py"
        probe.write_text("""import os,json
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["RG_AUTO_EDIT_BACKEND"]=os.getcwd()
from PySide6.QtWidgets import QApplication,QTableWidgetItem
from PySide6.QtCore import Qt
from rg_studio_ui import StudioWindow
app=QApplication([])
w=StudioWindow();w.resize(1920,1080);w.show()
try:w.tabs.setCurrentIndex(6)
except Exception:pass
for _ in range(6):app.processEvents()
t=w.thumb_table
t.setRowCount(3)
rows=[("882-1","03:18","A"),("883-2","11:14","B"),("887-1","02:54","C")]
for r,(did,dur,path) in enumerate(rows):
    chk=QTableWidgetItem("");chk.setCheckState(Qt.CheckState.Unchecked);t.setItem(r,0,chk)
    t.setItem(r,1,QTableWidgetItem(did))
    t.setItem(r,2,QTableWidgetItem(dur))
    t.setItem(r,3,QTableWidgetItem(path))
t.selectRow(0)
t.horizontalHeader().sectionClicked.emit(2)
for _ in range(3):app.processEvents()
desc=[t.item(r,2).text() for r in range(t.rowCount())]
t.horizontalHeader().sectionClicked.emit(2)
for _ in range(3):app.processEvents()
asc=[t.item(r,2).text() for r in range(t.rowCount())]
hidden=t.isColumnHidden(3)
video_h=w.thumb_video.minimumHeight()
table_w=t.width()
player_w=w.thumb_video.parentWidget().width()
shot=os.path.join(os.getcwd(),"PACK312_PREVIEW_1920x1080.png")
saved=w.grab().save(shot)
ok=(hidden and desc==["11:14","03:18","02:54"] and asc==["02:54","03:18","11:14"] and video_h>=250 and player_w>table_w and saved)
print("PACK312_PROBE|"+json.dumps({"passed":ok,"file_hidden":hidden,"desc":desc,"asc":asc,"video_min_h":video_h,"table_w":table_w,"player_w":player_w,"shot":shot},ensure_ascii=False))
raise SystemExit(0 if ok else 7)
""",encoding="utf-8")
        up=subprocess.run([smoke_py,"-X","utf8",str(probe)],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
        if up.returncode!=0 or "PACK312_PROBE|" not in (up.stdout or ""):
            raise RuntimeError("PACK312 UI probe failed: "+(up.stdout or "")[-12000:]+(up.stderr or "")[-12000:])
        preview=dry/"PACK312_PREVIEW_1920x1080.png"
        shutil.copy2(preview,root/preview.name)

        files=[]
        for p in [inst,rn,root/preview.name]:
            files.append({"path":p.name,"sha256":_sha(p),"size":p.stat().st_size})
        manifest={
          "schema":"RG_UPDATE_MANIFEST_V2",
          "product":"RG Auto Edit Studio",
          "studio_version":VERSION,
          "channel":"STABLE",
          "summary":"PACK312 preview-only hotfix: numeric duration sorting, hidden FILE column, larger player.",
          "created_at":time.time(),
          "files":files,
          "core_modified":False,
          "ui_only":True,
          "expected_ui_change":True,
          "base":"current live Studio 0.20.7.0",
          "safety":{"preview_only":True,"original_source_direct_locked":True,"rollback":True}
        }
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
            if hashlib.sha256(b).hexdigest()!=row["sha256"] or len(b)!=row["size"]:
                raise RuntimeError("manifest mismatch "+row["path"])

    return {
      "status":"READY","version":VERSION,"pack":PACK,
      "zip":str(zip_path),"nas_copy":str(nas_copy),
      "size":zip_path.stat().st_size,"sha256":_sha(zip_path),
      "tested_against_current_live_copy":True,
      "duration_sort":"PASS","file_hidden":"PASS","player_larger":"PASS",
      "compile":"PASS","ui_probe":"PASS","crc":"PASS","manifest":"PASS","installed":False
    }
