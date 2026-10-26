#!/usr/bin/env python3
"""Surgical, backed-up RG Auto Edit multi-dialogue selective retry guard.

This installer ONLY modifies the orchestration Python source when --apply is
requested; it NEVER runs a stream or writes video/audio/XML files. It preserves
every pre-existing completed dialogue and identity hold in the CURRENT manifest
when RG_ONLY_DIALOGUE_INDEXES is set, while preserving legacy behavior when
the environment variable is absent.
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
TARGET="rg_multi_dialogue.py"
EXPECTED_STUDIO_VERSION="0.20.20.14"

ANCHOR_A="""    manifest={
        'version':MANIFEST_VERSION,"""

PATCH_A="""    # RG_BATCH_SELECTIVE_RETRY_V1: explicit targeted repair preserves all
    # unrelated finished XML and unresolved identity holds in this manifest.
    _rg_selected_raw=os.environ.get('RG_ONLY_DIALOGUE_INDEXES','').strip()
    _rg_selected=set()
    _rg_old_holds={}
    _rg_manifest_backup_path=None
    if _rg_selected_raw:
        if os.environ.get('RG_ONLY_DIALOGUE_INDEX','').strip() not in ('','0'):
            raise RuntimeError('Conflicting selective and legacy single-dialogue retry')
        if not re.fullmatch(r'[1-9][0-9]*(?:,[1-9][0-9]*)*',_rg_selected_raw):
            raise RuntimeError('Invalid selective dialogue index list')
        _rg_parts=[int(x) for x in _rg_selected_raw.split(',')]
        _rg_selected=set(_rg_parts)
        if len(_rg_parts)!=len(_rg_selected) or not all(1<=x<=total for x in _rg_selected):
            raise RuntimeError('Selective dialogue indexes duplicate/out of range')
        if (str(old_manifest.get('stream'))!=stream
            or str(old_manifest.get('status')) not in ('PARTIAL_REVIEW','DIALOGUES_COMPLETE')
            or int(old_manifest.get('dialogue_count') or 0)!=total):
            raise RuntimeError('Selective retry requires completed/partial matching original manifest')
        for _h in old_manifest.get('review_holds') or []:
            if not isinstance(_h,dict):
                raise RuntimeError('Invalid saved hold row')
            _idx=int(_h.get('index') or 0)
            if _idx<1 or _idx>total or _idx in _rg_old_holds:
                raise RuntimeError('Unexpected saved hold index')
            _rg_old_holds[_idx]=_h
        if (set(resume_rows)&set(_rg_old_holds)
            or set(resume_rows)|set(_rg_old_holds)!=set(range(1,total+1))):
            raise RuntimeError('Previous manifest does not cover all dialogues uniquely')
        for _idx,(_shot,_job,_path,_found) in enumerate(jobs,1):
            if _idx in _rg_selected:
                continue
            _old=resume_rows.get(_idx)
            if _old is not None:
                _prior_xml=Path(str(_old.get('xml') or ''))
                if (not _prior_xml.is_file() or _prior_xml.stat().st_size<=0
                    or not verify_xml_lock(_prior_xml).get('ok')
                    or str(_old.get('screenshot') or '')!=str(_shot)):
                    raise RuntimeError(f'Selective retry cannot preserve unverified XML for {_idx}')
            else:
                _hold=_rg_old_holds.get(_idx) or {}
                _hold_path=Path(str(_hold.get('hold_path') or ''))
                if (str(_hold.get('status'))!='HOLD_FOR_REVIEW'
                    or not _hold_path.is_file()
                    or str(_hold.get('screenshot') or '')!=str(_shot)):
                    raise RuntimeError(f'Selective retry cannot preserve review hold for {_idx}')
        _rg_manifest_backup_path=manifest_path.with_name(
            manifest_path.stem+'_PRE_SELECTIVE_'+time.strftime('%Y%m%d_%H%M%S')+'.json')
        shutil.copy2(manifest_path,_rg_manifest_backup_path)
        print('RGSELECTIVE|START|'+','.join(str(i) for i in sorted(_rg_selected))+
              '|backup='+str(_rg_manifest_backup_path),flush=True)

    manifest={
        'version':MANIFEST_VERSION,"""

ANCHOR_B="""        prior=resume_rows.get(i) or {}
        prior_xml=Path(prior.get('xml') or output_path)"""

PATCH_B="""        prior=resume_rows.get(i) or {}
        # RG_BATCH_SELECTIVE_RETRY_V1: no child launch or XML publishing for
        # unselected records. Reuse only the preflight-verified previous record.
        if _rg_selected and i not in _rg_selected:
            if prior:
                _kept=dict(prior)
                _kept['index']=i
                manifest['outputs'].append(_kept)
                print(f'RGSELECTIVE|DIALOGUE|{i}|PRESERVED_XML',flush=True)
            else:
                manifest.setdefault('review_holds',[]).append(dict(_rg_old_holds[i]))
                print(f'RGSELECTIVE|DIALOGUE|{i}|PRESERVED_HOLD',flush=True)
            manifest['completed_dialogues']=len(manifest.get('outputs') or [])
            manifest['updated_at']=time.time()
            save_json(manifest_path,manifest)
            continue
        prior_xml=Path(prior.get('xml') or output_path)"""

ANCHOR_C="""        if can_resume:
            print(f'RGRESUME|DIALOGUE|{i}|READY|reuse completed dialogue XML',flush=True)"""

PATCH_C="""        if _rg_selected and os.environ.get('RG_FORCE_SELECTED_DIALOGUES','0')=='1':
            # Preserve the old XML as a separate revision; selected recompute
            # must never silently return the same cached XML.
            can_resume=False
        if can_resume:
            print(f'RGRESUME|DIALOGUE|{i}|READY|reuse completed dialogue XML',flush=True)"""

ANCHOR_D="""        except Exception as exc:
            manifest.update(status='FAILED', failed_dialogue=i, error=str(exc), updated_at=time.time())
            save_json(manifest_path,manifest)
            raise"""

PATCH_D="""        except Exception as exc:
            manifest.update(status='FAILED', failed_dialogue=i, error=str(exc), updated_at=time.time())
            save_json(manifest_path,manifest)
            if _rg_selected and _rg_manifest_backup_path is not None:
                # Recover the entire previous authoritative manifest; all
                # existing XML revisions are preserved on disk.
                shutil.copy2(_rg_manifest_backup_path,manifest_path)
                print('RGSELECTIVE|ROLLBACK|MANIFEST_RESTORED',flush=True)
            raise"""

ANCHOR_E="""    # Preserve all prior delivered XMLs and revisions, even when a later run
    # succeeds. Only outputs enumerated in the CURRENT manifest are current."""

PATCH_E="""    # RG_BATCH_SELECTIVE_RETRY_V1: only finalize a full, uniquely covered
    # manifest. Partial identity holds must remain holds, never PASS.
    if _rg_selected:
        _rg_indices=[int(x.get('index') or 0) for x in manifest.get('outputs') or []]
        _rg_hold_indices=[int(x.get('index') or 0) for x in manifest.get('review_holds') or []]
        if (len(_rg_indices)!=len(set(_rg_indices))
            or len(_rg_hold_indices)!=len(set(_rg_hold_indices))
            or set(_rg_indices)&set(_rg_hold_indices)
            or set(_rg_indices)|set(_rg_hold_indices)!=set(range(1,total+1))):
            if _rg_manifest_backup_path is not None:
                shutil.copy2(_rg_manifest_backup_path,manifest_path)
            raise RuntimeError('Selective retry cannot publish incomplete/duplicate dialogue manifest')
        manifest['outputs'].sort(key=lambda r:int(r['index']))
        manifest.setdefault('review_holds',[]).sort(key=lambda r:int(r['index']))
        manifest['completed_dialogues']=len(manifest['outputs'])
        manifest['updated_at']=time.time()
        save_json(manifest_path,manifest)
        print('RGSELECTIVE|FINAL|'+','.join(str(i) for i in sorted(_rg_selected))+
              f'|ready={len(_rg_indices)}|held={len(_rg_hold_indices)}',flush=True)

    # Preserve all prior delivered XMLs and revisions, even when a later run
    # succeeds. Only outputs enumerated in the CURRENT manifest are current."""

PATCHES=((ANCHOR_A,PATCH_A),(ANCHOR_B,PATCH_B),(ANCHOR_C,PATCH_C),
         (ANCHOR_D,PATCH_D),(ANCHOR_E,PATCH_E))

def patch_source(source: str):
    if all("RG_BATCH_SELECTIVE_RETRY_V1" in source for _ in [0]) and PATCH_A in source:
        if not all(replacement in source for _,replacement in PATCHES):
            raise RuntimeError("Partial selective retry patch detected, no overwrite allowed")
        ast.parse(source)
        return source,"ALREADY_PATCHED"
    for i,(original,replacement) in enumerate(PATCHES,1):
        if source.count(original)!=1 or replacement in source:
            raise RuntimeError(f"Unexpected installed orchestration source anchor {i}, refuse patch")
    result=source
    for original,replacement in PATCHES:
        result=result.replace(original,replacement,1)
    ast.parse(result)
    return result,"PATCH_READY"

def planned_preservation(outputs,holds,selected,total):
    """Pure fail-closed model of the source manifest precondition."""
    selected=set(selected)
    if not selected or any(not isinstance(i,int) or i<1 or i>total for i in selected):
        raise RuntimeError("Invalid selection")
    output_ids=[int(x.get("index",0)) for x in outputs]
    hold_ids=[int(x.get("index",0)) for x in holds]
    if (len(output_ids)!=len(set(output_ids)) or len(hold_ids)!=len(set(hold_ids))
        or set(output_ids)&set(hold_ids)
        or set(output_ids)|set(hold_ids)!=set(range(1,total+1))):
        raise RuntimeError("Manifest prior coverage invalid")
    preserved_outputs=[dict(x) for x in outputs if int(x["index"]) not in selected]
    preserved_holds=[dict(x) for x in holds if int(x["index"]) not in selected]
    return preserved_outputs,preserved_holds

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    source=APP/TARGET
    version=APP/"rg_studio_version.py"
    if not source.is_file() or not version.is_file():
        raise RuntimeError("Installed Studio source/runtime missing")
    if not re.search(r'STUDIO_VERSION\s*=\s*["\x27]0\.20\.20\.14["\x27]',
                     version.read_text(encoding="utf-8-sig")):
        raise RuntimeError("Unsupported installed Studio version")
    original=source.read_text(encoding="utf-8-sig")
    updated,status=patch_source(original)
    result={"schema":"RG_SELECTIVE_DIALOGUE_RETRY_PATCH_V1","status":status,
            "applied":False,"media_writes":0,"xml_writes":0,
            "dialogue_processing_started":False}
    if args.apply and status=="PATCH_READY":
        backup=DATA/"release_backups"/("PRE_SELECTIVE_DIALOGUE_RETRY_"+
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True,exist_ok=False)
        saved=backup/TARGET
        shutil.copy2(source,saved)
        tmp=source.with_name(TARGET+".selective-new")
        try:
            tmp.write_text(updated,encoding="utf-8")
            if tmp.read_text(encoding="utf-8")!=updated:
                raise RuntimeError("Source write verification mismatch")
            ast.parse(tmp.read_text(encoding="utf-8"))
            os.replace(tmp,source)
            _src,_state=patch_source(source.read_text(encoding="utf-8-sig"))
            if _state!="ALREADY_PATCHED":
                raise RuntimeError("Installed patch validation failed")
            result.update(status="APPLIED",applied=True,backup=str(saved))
        except Exception:
            shutil.copy2(saved,source)
            raise
        finally:
            tmp.unlink(missing_ok=True)
    print("RG_SELECTIVE_DIALOGUE_RETRY_PATCH|"+json.dumps(result,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
