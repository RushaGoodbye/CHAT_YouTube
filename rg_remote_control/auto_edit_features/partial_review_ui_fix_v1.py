#!/usr/bin/env python3
"""Guarded hotfix for RG Auto Edit Studio partial-review QA and queue UX.

Dry-run by default. --apply backs up the UI and atomically changes only that
Python module; never changes stream XMLs, media, manifest or QA report.
"""
from __future__ import annotations
import argparse
import ast
import datetime
import json
import os
import re
import shutil
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
NAME="rg_studio_ui.py"
OLD_QA="""            if (str(data.get('stream'))!=stream
                or str(data.get('status'))!='DIALOGUES_COMPLETE'
                or expected<=0 or len(data.get('outputs') or [])!=expected):
                raise RuntimeError('Манифест не підтверджує завершення всіх діалогів')
            from rg_studio_postrun import _primary_outputs
            outputs=_primary_outputs(APP_DIR/stream,[],stream)
            if len(outputs)!=expected or not all(x.is_file() and x.stat().st_size>0 for x in outputs):
                raise RuntimeError('Не всі XML з поточного манифесту доступні')"""
NEW_QA="""            _manifest_rows=data.get('outputs') or []
            _manifest_holds=data.get('review_holds') or []
            _complete=(str(data.get('status'))=='DIALOGUES_COMPLETE'
                       and expected>0 and len(_manifest_rows)==expected)
            _completed_ids={int(x.get('index') or 0) for x in _manifest_rows if isinstance(x,dict)}
            _held_ids={int(x.get('index') or 0) for x in _manifest_holds if isinstance(x,dict)}
            _partial=(str(data.get('status'))=='PARTIAL_REVIEW'
                      and expected>0 and bool(_manifest_rows) and bool(_manifest_holds)
                      and len(_manifest_rows)+len(_manifest_holds)==expected
                      and len(_completed_ids)==len(_manifest_rows)
                      and len(_held_ids)==len(_manifest_holds)
                      and not (_completed_ids & _held_ids)
                      and (_completed_ids | _held_ids)==set(range(1,expected+1))
                      and all(str(h.get('status') or '')=='HOLD_FOR_REVIEW'
                              for h in _manifest_holds if isinstance(h,dict)))
            if str(data.get('stream'))!=stream or not (_complete or _partial):
                raise RuntimeError('Манифест не підтверджує завершення або контрольовану часткову готовність діалогів')
            from rg_studio_postrun import _primary_outputs
            outputs=_primary_outputs(APP_DIR/stream,[],stream)
            if len(outputs)!=len(_manifest_rows) or not all(x.is_file() and x.stat().st_size>0 for x in outputs):
                raise RuntimeError('Не всі наявні XML з поточного манифесту доступні')"""

OLD_POST="""        passed=bool(result and result.get("passed") and int(code)==0)
        # R6: independently evaluate current-manifest cigarette evidence before"""
NEW_POST="""        passed=bool(result and result.get("passed") and int(code)==0)
        # RG_PARTIAL_REVIEW_UI_V1: keep valid primary XMLs available; do not
        # promote the unfinished stream to PASS or waive guest identity holds.
        self._rg_partial_review_pending=False
        self._rg_partial_review_detail=''
        try:
            _s=self.metric_stream.text().strip()
            _m=APP_DIR/f'RG_EDITED_{_s}_MULTI_DIALOGUE.json'
            if result and not passed and _s.isdigit() and _m.is_file():
                _d=json.loads(_m.read_text(encoding='utf-8-sig'))
                _rows=_d.get('outputs') or [];_holds=_d.get('review_holds') or []
                _total=int(_d.get('dialogue_count') or 0)
                _done={int(r.get('index') or 0) for r in _rows if isinstance(r,dict)}
                _held={int(h.get('index') or 0) for h in _holds if isinstance(h,dict)}
                _checks={str(c.get('name')):bool(c.get('ok')) for c in result.get('checks',[]) if isinstance(c,dict)}
                _required=('XML створено','XML існують','XML синтаксис',
                           'Аудіо ORIGINAL SOURCE','Перевірка XML',
                           'Контроль меж','Premiere сумісність')
                _valid=(str(_d.get('stream'))==_s and _d.get('status')=='PARTIAL_REVIEW'
                        and _total>0 and bool(_rows) and bool(_holds)
                        and _total==len(_rows)+len(_holds)
                        and len(_done)==len(_rows) and len(_held)==len(_holds)
                        and not (_done & _held) and (_done|_held)==set(range(1,_total+1))
                        and all(_checks.get(name,False) for name in _required)
                        and int(result.get('xml_count') or 0)==len(_rows))
                if _valid:
                    self._rg_partial_review_pending=True
                    self._rg_partial_review_progress=f'{round(100*len(_rows)/_total)}%'
                    self._rg_partial_review_detail=(f'Готові XML: {len(_rows)}/{_total}; '
                        f'потребують перевірки гостя: {", ".join(str(i) for i in sorted(_held))}')
                    self._log('RG_PARTIAL_REVIEW_UI|'+self._rg_partial_review_detail)
        except Exception as _partial_exc:
            self._log('RG_PARTIAL_REVIEW_UI_AUDIT_ERROR|'+repr(_partial_exc))
        # R6: independently evaluate current-manifest cigarette evidence before"""

OLD_BATCH="""            if getattr(self,'_rg_manual_review_pending',False):
                self._batch_set(cur,status='ПЕРЕВІРКА',progress='99%',stage='CIGARETTE_REVIEW',
                                eta='—',detail='QA пройдено • маркери куріння потребують перевірки')
            else:
                self._batch_set(cur,status="ГОТОВО" if previous_ok else "ПОМИЛКА",
                                progress="100%" if previous_ok else None,stage="DONE" if previous_ok else "ERROR",
                                eta="—",detail="Завершено" if previous_ok else "Помилка • можна повторити")
        self._rg_manual_review_pending=False"""
NEW_BATCH="""            if getattr(self,'_rg_manual_review_pending',False):
                self._batch_set(cur,status='ПЕРЕВІРКА',progress='99%',stage='CIGARETTE_REVIEW',
                                eta='—',detail='QA пройдено • маркери куріння потребують перевірки')
            elif getattr(self,'_rg_partial_review_pending',False) and not previous_ok:
                self._batch_set(cur,status='ПЕРЕВІРКА',
                                progress=getattr(self,'_rg_partial_review_progress','—'),
                                stage='IDENTITY_REVIEW',eta='—',
                                detail=getattr(self,'_rg_partial_review_detail','Частина XML готова • перевірка гостя'))
            else:
                self._batch_set(cur,status="ГОТОВО" if previous_ok else "ПОМИЛКА",
                                progress="100%" if previous_ok else None,stage="DONE" if previous_ok else "ERROR",
                                eta="—",detail="Завершено" if previous_ok else "Помилка • можна повторити")
        self._rg_manual_review_pending=False
        self._rg_partial_review_pending=False"""

PAIRS=((OLD_QA,NEW_QA),(OLD_POST,NEW_POST),(OLD_BATCH,NEW_BATCH))

def patch_source(src):
    if all(b in src for _,b in PAIRS):
        ast.parse(src)
        return src,"ALREADY_PATCHED"
    for i,(old,new) in enumerate(PAIRS):
        if src.count(old)!=1:raise RuntimeError(f"Source anchor #{i+1} mismatch, refusing hotfix")
        if new in src:raise RuntimeError("Partial application detected; refusing hotfix")
    out=src
    for old,new in PAIRS:out=out.replace(old,new,1)
    ast.parse(out)
    return out,"PATCH_READY"

def main():
    arg=argparse.ArgumentParser()
    arg.add_argument("--apply",action="store_true")
    args=arg.parse_args()
    ui=APP/NAME;version=APP/"rg_studio_version.py"
    if not ui.is_file() or not version.is_file():raise RuntimeError("Studio not installed")
    if not re.search(r'STUDIO_VERSION\s*=\s*["\x27]0\.20\.20\.14["\x27]',
                     version.read_text(encoding="utf-8-sig")):
        raise RuntimeError("Unknown live Studio version, cannot modify")
    orig=ui.read_text(encoding="utf-8-sig")
    updated,state=patch_source(orig)
    status={"schema":"RG_AUTO_EDIT_PARTIAL_REVIEW_UI_HOTFIX_V1","status":state,
            "syntax":"PASS","media_writes":0,"xml_writes":0,
            "reports_unchanged":True,"applied":False}
    if args.apply and state=="PATCH_READY":
        backup=DATA/"release_backups"/("PRE_PARTIAL_REVIEW_UI_"+
                 datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True,exist_ok=False)
        saved=backup/NAME
        shutil.copy2(ui,saved)
        pending=ui.with_name(NAME+".partial-next")
        try:
            pending.write_text(updated,encoding="utf-8")
            if pending.read_text(encoding="utf-8")!=updated:
                raise RuntimeError("Write verification failed")
            ast.parse(pending.read_text(encoding="utf-8"))
            os.replace(pending,ui)
            chk,mode=patch_source(ui.read_text(encoding="utf-8-sig"))
            if mode!="ALREADY_PATCHED":raise RuntimeError("Post-update validation failed")
            status.update(status="APPLIED",applied=True,backup=str(saved))
        except Exception:
            shutil.copy2(saved,ui)
            raise
        finally:
            pending.unlink(missing_ok=True)
    print("RG_PARTIAL_REVIEW_UI_FIX|"+json.dumps(status,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
