from __future__ import annotations
import hashlib,json,os,re,shutil,subprocess,sys,tempfile,time,zipfile,py_compile
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNTIME_PY=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
VERSION="0.20.31.1"
PACK="PACK311"
NAME=f"RG_AUTO_EDIT_STUDIO_UPDATE_{VERSION}_{PACK}_PREVIEW_SORT_PLAYER.zip"

def _sha(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def _find_base()->Path:
    names=[
        "RG_AUTO_EDIT_STUDIO_UPDATE_0.20.31.0_PACK310_LIVE_TELEMETRY.zip",
        "RG_AUTO_EDIT_STUDIO_UPDATE_0.20.30.0_PACK300.zip",
    ]
    for n in names:
        for p in (DATA/"PACKAGES"/n,Path.home()/"Downloads"/n):
            if p.is_file():
                return p
    raise RuntimeError("PACK310/PACK300 base archive not found")

def build_auto_edit_pack311_update()->dict:
    if os.name!="nt":
        raise RuntimeError("Windows only")
    if not APP.is_dir():
        raise RuntimeError("RG Auto Edit app not found")

    base=_find_base()
    with zipfile.ZipFile(base) as z:
        installer_name="INSTALL_PACK310.py" if "INSTALL_PACK310.py" in z.namelist() else "INSTALL_PACK300.py"
        base_installer=z.read(installer_name).decode("utf-8")

    downloads=Path.home()/"Downloads";downloads.mkdir(parents=True,exist_ok=True)
    packages=DATA/"PACKAGES";packages.mkdir(parents=True,exist_ok=True)
    zip_path=downloads/NAME
    nas_copy=packages/NAME

    preview_module=r'''from __future__ import annotations
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
        item.setCheckState(old.checkState())
        for role in (Qt.ItemDataRole.ToolTipRole,Qt.ItemDataRole.StatusTipRole):
            val=old.data(role)
            if val is not None:item.setData(role,val)
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
    table.setSortingEnabled(False)
    try:
        _convert_duration_cells(table)
        order=getattr(host,"_thumb_duration_sort_order",Qt.SortOrder.DescendingOrder)
        table.setSortingEnabled(True)
        table.sortItems(2,order)
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
    # Keep the path column internally for compatibility with playback/selection,
    # but hide it from the user because the base directory is constant.
    table.setColumnHidden(3,True)
    hdr=table.horizontalHeader()
    hdr.setSectionsClickable(True)
    hdr.setSortIndicatorShown(True)
    hdr.setSortIndicator(2,Qt.SortOrder.DescendingOrder)
    try:
        hdr.setSectionResizeMode(0,QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1,QHeaderView.Stretch)
        hdr.setSectionResizeMode(2,QHeaderView.ResizeToContents)
    except Exception:
        pass
    table.setToolTip("Клік по колонці «ТРИВАЛІСТЬ» - сортування від довгих до коротких / навпаки.")
    host._thumb_duration_sort_order=Qt.SortOrder.DescendingOrder
    hdr.sectionClicked.connect(lambda section: sort_duration(host,table) if int(section)==2 else None)
'''

    installer="from __future__ import annotations\nBASE_INSTALLER="+repr(base_installer)+"\nPACK311_PREVIEW="+repr(preview_module)+"\n"+r'''
import json,os,re,shutil,sys,time,traceback,py_compile
from pathlib import Path
APP=Path.cwd()
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
if os.environ.get("RG_PACK311_DRYRUN"):DATA=APP/"_PACK311_DATA"
VERSION="0.20.31.1"

def atomic(p,text):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".pack311.tmp");t.write_text(text,encoding="utf-8");os.replace(t,p)

def snapshot():
    root=DATA/"release_backups"/("PRE_PACK311_"+time.strftime("%Y%m%d_%H%M%S"));root.mkdir(parents=True,exist_ok=True)
    names=["rg_studio_ui.py","rg_auto_edit_config.json","rg_studio_version.py","rg_pack311_preview.py","rg_pack311_selftest.py"]
    ex={}
    for n in names:
        p=APP/n;ex[n]=p.exists()
        if p.is_file():shutil.copy2(p,root/n)
    (root/"_existed.json").write_text(json.dumps(ex),encoding="utf-8")
    return root,ex

def restore(root,ex):
    for n,was in ex.items():
        src=root/n;dst=APP/n
        if src.is_file():shutil.copy2(src,dst)
        elif not was and dst.exists():
            try:dst.unlink()
            except Exception:pass

def apply_base():
    ns={"__name__":"rg_pack311_base","__file__":str(APP/"<embedded_base>")}
    exec(compile(BASE_INSTALLER,"<embedded_base>","exec"),ns)
    rc=ns["main"]()
    if rc not in (0,None):raise RuntimeError("Embedded base failed: "+str(rc))

def patch_ui():
    p=APP/"rg_studio_ui.py";s=p.read_text(encoding="utf-8")
    if "from rg_pack311_preview import install_preview_table" not in s:
        anchor="from rg_internal_browser import RGInternalBrowser\n"
        if anchor in s:
            s=s.replace(anchor,anchor+"from rg_pack311_preview import install_preview_table\n",1)
        else:
            raise RuntimeError("preview import anchor missing")

    # Header stays 4 columns internally. FILE remains hidden for compatibility.
    old='self.thumb_table=QTableWidget(0,4);self.thumb_table.setHorizontalHeaderLabels(["✓","ДІАЛОГ","ТРИВАЛІСТЬ","ФАЙЛ"])'
    new='self.thumb_table=QTableWidget(0,4);self.thumb_table.setHorizontalHeaderLabels(["✓","ДІАЛОГ","ТРИВАЛІСТЬ","ФАЙЛ"])'
    if old not in s:
        raise RuntimeError("thumbnail table anchor missing")
    s=s.replace(old,new,1)

    # Install numeric duration sorting + hide FILE after current header setup.
    anchor='self.thumb_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)'
    if anchor not in s:
        raise RuntimeError("thumbnail header anchor missing")
    if "RG_PACK311_PREVIEW_TABLE" not in s:
        s=s.replace(anchor,anchor+'\n        # RG_PACK311_PREVIEW_TABLE\n        install_preview_table(self,self.thumb_table)',1)

    # Give the player the majority of the horizontal space.
    if 'media_row.addWidget(self.thumb_table,3)' in s:
        s=s.replace('media_row.addWidget(self.thumb_table,3)','media_row.addWidget(self.thumb_table,2)',1)
    if 'media_row.addWidget(pg,2)' in s:
        s=s.replace('media_row.addWidget(pg,2)','media_row.addWidget(pg,4)',1)
    elif 'media_row.addWidget(pg,3)' in s:
        s=s.replace('media_row.addWidget(pg,3)','media_row.addWidget(pg,4)',1)
    else:
        # Fallback: the group must be added somewhere after its construction.
        marker='self.thumb_player.setVideoOutput(self.thumb_video)'
        if marker not in s:
            raise RuntimeError("thumbnail player group anchor missing")

    # Increase useful player viewport without taking over the entire page.
    s=s.replace('self.thumb_video.setMinimumHeight(130);self.thumb_video.setMaximumHeight(150)',
                'self.thumb_video.setMinimumHeight(210);self.thumb_video.setMaximumHeight(280)',1)

    atomic(p,s)

def patch_config():
    p=APP/"rg_auto_edit_config.json";d=json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
    d["pack311"]={
      "schema":"RG_PACK311_PREVIEW_V1","enabled":True,"version":VERSION,
      "preview_dialogues":{
        "duration_sort":True,"duration_sort_numeric_seconds":True,"duration_sort_toggle":True,
        "file_column_visible":False,"file_column_kept_internal":True,
        "player_width_priority":True,"table_player_stretch":[2,4],
        "player_min_height":210,"player_max_height":280,
        "selection_preserved_during_sort":True
      },
      "safety":{"preview_only":True,"editing_core_untouched":True,"original_source_direct_locked":True}
    }
    atomic(p,json.dumps(d,ensure_ascii=False,indent=2))

def patch_version():
    p=APP/"rg_studio_version.py";s=p.read_text(encoding="utf-8") if p.is_file() else ""
    s=re.sub(r'STUDIO_VERSION\s*=\s*"[^"]+"',f'STUDIO_VERSION="{VERSION}"',s)
    if "STUDIO_VERSION" not in s:s='STUDIO_VERSION="'+VERSION+'"\n'+s
    if "RG_FEATURE_PACK" in s:s=re.sub(r'RG_FEATURE_PACK\s*=\s*"[^"]+"','RG_FEATURE_PACK="PACK311"',s)
    else:s+='\nRG_FEATURE_PACK="PACK311"\n'
    atomic(p,s)

def write_selftest():
    code="""from __future__ import annotations
import json,py_compile
from pathlib import Path
APP=Path(__file__).resolve().parent
def main():
    checks=[]
    def add(n,ok,d=""):checks.append({"name":n,"ok":bool(ok),"detail":str(d)})
    for n in ["rg_studio_ui.py","rg_pack311_preview.py"]:
        try:py_compile.compile(str(APP/n),doraise=True);add("compile "+n,True)
        except Exception as e:add("compile "+n,False,e)
    ui=(APP/"rg_studio_ui.py").read_text(encoding="utf-8",errors="replace")
    add("preview helper imported","from rg_pack311_preview import install_preview_table" in ui)
    add("file column hidden hook","RG_PACK311_PREVIEW_TABLE" in ui)
    add("table stretch 2","media_row.addWidget(self.thumb_table,2)" in ui)
    add("player stretch 4","media_row.addWidget(pg,4)" in ui)
    add("player height","setMinimumHeight(210)" in ui and "setMaximumHeight(280)" in ui)
    cfg=json.loads((APP/"rg_auto_edit_config.json").read_text(encoding="utf-8-sig"))
    add("pack311 enabled",bool((cfg.get("pack311") or {}).get("enabled")))
    passed=all(x["ok"] for x in checks)
    print("RG_PACK311_SELFTEST|"+json.dumps({"passed":passed,"result":"READY FOR PRODUCTION" if passed else "BLOCKED","checks":checks},ensure_ascii=False))
    return 0 if passed else 3
if __name__=="__main__":raise SystemExit(main())
"""
    atomic(APP/"rg_pack311_selftest.py",code)

def main():
    b,ex=snapshot()
    try:
        apply_base()
        atomic(APP/"rg_pack311_preview.py",PACK311_PREVIEW)
        patch_ui();patch_config();patch_version();write_selftest()
        for n in ["rg_studio_ui.py","rg_pack311_preview.py","rg_pack311_selftest.py","rg_studio_version.py"]:
            if (APP/n).is_file():py_compile.compile(str(APP/n),doraise=True)
        print("PACK311_BACKUP|"+str(b));print("PACK311_INSTALL|PASS");return 0
    except Exception:
        traceback.print_exc();restore(b,ex);print("PACK311_INSTALL|ROLLBACK");return 10
if __name__=="__main__":raise SystemExit(main())
'''

    notes="""RG Auto Edit PACK311 - Preview Dialogue Sort + Larger Player

Зміни у вкладці ПРЕВ'Ю:
- числове сортування по ТРИВАЛІСТЬ кліком по заголовку;
- перший клік: довгі -> короткі, наступний: короткі -> довгі;
- колонка ФАЙЛ прихована з інтерфейсу;
- шлях залишається внутрішньо, щоб не ламати playback/selection;
- ширина блоку список/плеєр змінена приблизно з 60/40 на 33/67;
- плеєр збільшений по висоті до 210-280 px;
- поточний вибір діалогу зберігається після сортування;
- ядро монтажу та аудіо не змінюються.
"""

    with tempfile.TemporaryDirectory(prefix="rg_pack311_build_") as td:
        td=Path(td);root=td/"RG_PACK311";root.mkdir()
        inst=root/"INSTALL_PACK311.py";inst.write_text(installer,encoding="utf-8")
        rn=root/"RELEASE_NOTES_PACK311.txt";rn.write_text(notes,encoding="utf-8")
        dry=td/"dry_app";shutil.copytree(APP,dry,dirs_exist_ok=True)
        env=os.environ.copy();env.update({"RG_PACK170_DRYRUN":"1","RG_PACK200_DRYRUN":"1","RG_PACK300_DRYRUN":"1","RG_PACK310_DRYRUN":"1","RG_PACK311_DRYRUN":"1","PYTHONUTF8":"1"})
        cp=subprocess.run([sys.executable,"-X","utf8",str(inst)],cwd=str(dry),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=360)
        if cp.returncode!=0:
            raise RuntimeError("PACK311 dry-run failed: "+(cp.stdout or "")[-12000:]+(cp.stderr or "")[-12000:])

        for n in ["rg_studio_ui.py","rg_pack311_preview.py","rg_pack311_selftest.py"]:
            py_compile.compile(str(dry/n),doraise=True)

        smoke_py=str(RUNTIME_PY if RUNTIME_PY.is_file() else Path(sys.executable))
        pe={**env,"QT_QPA_PLATFORM":"offscreen","RG_AUTO_EDIT_BACKEND":str(dry)}
        sm=subprocess.run([smoke_py,"-X","utf8","-c","import rg_pack311_preview,rg_studio_ui;print('IMPORT_OK')"],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=90)
        if sm.returncode!=0 or "IMPORT_OK" not in (sm.stdout or ""):
            raise RuntimeError("PACK311 import smoke failed: "+(sm.stdout or "")[-8000:]+(sm.stderr or "")[-8000:])

        probe=dry/"_pack311_probe.py"
        probe.write_text("""import os,json
os.environ["QT_QPA_PLATFORM"]="offscreen";os.environ["RG_AUTO_EDIT_BACKEND"]=os.getcwd()
from PySide6.QtWidgets import QApplication,QTableWidgetItem
from PySide6.QtCore import Qt
from rg_studio_ui import StudioWindow
app=QApplication([]);w=StudioWindow();w.resize(1920,1080);w.show()
try:w.tabs.setCurrentIndex(6)
except Exception:pass
for _ in range(6):app.processEvents()
t=w.thumb_table
t.setRowCount(3)
rows=[("882-1","03:18","A"),("883-2","11:14","B"),("887-1","02:54","C")]
for r,(did,dur,path) in enumerate(rows):
    chk=QTableWidgetItem("");chk.setCheckState(Qt.CheckState.Unchecked);t.setItem(r,0,chk)
    t.setItem(r,1,QTableWidgetItem(did));t.setItem(r,2,QTableWidgetItem(dur));t.setItem(r,3,QTableWidgetItem(path))
t.horizontalHeader().sectionClicked.emit(2)
for _ in range(3):app.processEvents()
desc=[t.item(r,2).text() for r in range(t.rowCount())]
t.horizontalHeader().sectionClicked.emit(2)
for _ in range(3):app.processEvents()
asc=[t.item(r,2).text() for r in range(t.rowCount())]
hidden=t.isColumnHidden(3)
player_w=w.thumb_video.parentWidget().width();table_w=t.width()
shot=os.path.join(os.getcwd(),"PACK311_PREVIEW_1920x1080.png");saved=w.grab().save(shot)
ok=hidden and desc==["11:14","03:18","02:54"] and asc==["02:54","03:18","11:14"] and player_w>table_w and saved
print("PACK311_PROBE|"+json.dumps({"passed":ok,"file_hidden":hidden,"desc":desc,"asc":asc,"table_width":table_w,"player_group_width":player_w,"screenshot":shot},ensure_ascii=False))
raise SystemExit(0 if ok else 7)
""",encoding="utf-8")
        up=subprocess.run([smoke_py,"-X","utf8",str(probe)],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
        if up.returncode!=0 or "PACK311_PROBE|" not in (up.stdout or ""):
            raise RuntimeError("PACK311 UI probe failed: "+(up.stdout or "")[-10000:]+(up.stderr or "")[-10000:])
        preview=dry/"PACK311_PREVIEW_1920x1080.png";shutil.copy2(preview,root/preview.name)

        st=subprocess.run([smoke_py,"-X","utf8",str(dry/"rg_pack311_selftest.py")],cwd=str(dry),env=pe,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=70)
        if st.returncode!=0 or "READY FOR PRODUCTION" not in (st.stdout or ""):
            raise RuntimeError("PACK311 selftest failed: "+(st.stdout or "")[-7000:]+(st.stderr or "")[-7000:])

        files=[]
        for p in [inst,rn,root/preview.name]:
            files.append({"path":p.name,"sha256":_sha(p),"size":p.stat().st_size})
        manifest={
          "schema":"RG_UPDATE_MANIFEST_V2","product":"RG Auto Edit Studio","studio_version":VERSION,"channel":"STABLE",
          "summary":"PACK311: numeric duration sorting, hidden FILE column and enlarged dialogue player in Preview.",
          "created_at":time.time(),"files":files,"core_modified":False,"ui_only":True,"expected_ui_change":True,
          "base":"embedded PACK310/PACK300",
          "safety":{"original_source_direct_locked":True,"duration_sort_probe":True,"file_column_hidden_probe":True,"player_ratio_probe":True,"rollback":True}
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
    return {"status":"READY","version":VERSION,"pack":PACK,"zip":str(zip_path),"nas_copy":str(nas_copy),"size":zip_path.stat().st_size,"sha256":_sha(zip_path),
            "duration_sort":"PASS","file_column_hidden":"PASS","player_ratio":"PASS","dry_run":"PASS","compile":"PASS","import_smoke":"PASS","ui_probe":"PASS","selftest":"READY FOR PRODUCTION","crc":"PASS","manifest":"PASS","installed":False}
