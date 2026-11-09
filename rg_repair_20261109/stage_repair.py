"""RG Repair 2026-11-09: source patch staging only; never edits the active Studio.

Strictly scope fixes to current-run XML selection, safe face retry, and explicit
audio-input diagnostics. Ambiguous identity/real overlap MUST remain blocked.
"""
from __future__ import annotations
import ast
import hashlib
import json
import re
from pathlib import Path

PATCH_VERSION="RG_REPAIR_20261109_V1"
FILES=("rg_studio_postrun.py","rg_xml_verify_v51.py","rg_face_anchor_guard_v1.py",
       "rg_audalign_worker.py","rg_qa_current_result.py")

def replace_once(body,old,new,label):
    count=body.count(old)
    if count!=1:
        raise RuntimeError("ANCHOR_MISMATCH:"+label+":"+str(count))
    return body.replace(old,new,1)

def patch_postrun(s):
    s=replace_once(s,
        "_complete=(_status=='DIALOGUES_COMPLETE' and _expected==len(rows))",
        "_complete=(_status in ('DIALOGUES_COMPLETE','QA_FAILED') and _expected==len(rows))",
        "POSTRUN_QA_FAILED_COMPLETED")
    s=replace_once(s,
        "or str(m.get('status'))!='DIALOGUES_COMPLETE'",
        "or str(m.get('status')) not in ('DIALOGUES_COMPLETE','QA_FAILED')",
        "INVENTORY_STATUS")
    s=replace_once(s,
        "raw.name.casefold()==f'RG_EDITED_{stream}.xml'.casefold())",
        "bool(re.fullmatch(r'RG_EDITED_'+re.escape(str(stream))+r'(?:_R[1-9]\d*)?\.xml',raw.name,re.I)))",
        "SINGLE_REVISION_ID")
    s=replace_once(s,
        "filename.casefold()==f'RG_EDITED_{stream}.xml'.casefold())",
        "bool(re.fullmatch(r'RG_EDITED_'+re.escape(str(stream))+r'(?:_R[1-9]\d*)?\.xml',filename,re.I)))",
        "INVENTORY_SINGLE_REVISION_ID")
    return s

def patch_xml_verify(s):
    old='xmls=[Path(x) for x in (xml_paths or sorted(root.glob("RG_EDITED_*.xml"),key=_num)) if "_SHORTS" not in Path(x).stem and "_AUTO_BASELINE" not in Path(x).stem]'
    new='''xmls=[Path(x) for x in (xml_paths or sorted(root.glob("RG_EDITED_*.xml"),key=_num))
          if "_SHORTS" not in Path(x).stem.upper()
          and "_AUTO_BASELINE" not in Path(x).stem.upper()
          and "_UNCENSORED" not in Path(x).stem.upper()]
    # The verified current-run manifest alone selects active revisions.
    # If manifest exists but is malformed, fail closed; never scan stale files.
    if xml_paths is None:
        candidates=list(root.parent.glob("RG_EDITED_*_MULTI_DIALOGUE.json"))
        stream=root.name
        mpath=root.parent/("RG_EDITED_"+stream+"_MULTI_DIALOGUE.json")
        if mpath.is_file():
            try:
                manifest=json.loads(mpath.read_text(encoding="utf-8-sig"))
                rows=manifest.get("outputs") or []
                assert str(manifest.get("stream"))==stream
                assert str(manifest.get("status")) in ("QA_FAILED","DIALOGUES_COMPLETE")
                assert len(rows)==int(manifest.get("dialogue_count") or 0)>0
                expected=[root/Path(str(r.get("premiere_xml") or "")).name for r in rows]
                assert len(set(p.name.casefold() for p in expected))==len(expected)
                assert all(p.parent==root and p.is_file() for p in expected)
                xmls=expected
            except (ValueError,KeyError,TypeError,AssertionError,AttributeError) as exc:
                raise ValueError("CURRENT_XML_MANIFEST_UNVERIFIED: "+str(exc))
'''
    return replace_once(s,old,new,"XML_VERIFY_ACTIVE_REVISIONS")

def patch_face(s):
    old='''            if chosen is None:
                raise RuntimeError(f"{rec['path'].name}: FACE_ANCHOR_UNCONFIRMED; no repeated high-confidence face matches inside {lo:.1f}-{hi:.1f}")'''
    new='''            if chosen is None:
                # Last safe retry: denser sampling of a bounded local area,
                # with unchanged strict independent two-hit confidence gate.
                tight_lo=max(lo,original-120.0)
                tight_hi=min(hi,original+120.0)
                if tight_hi>tight_lo+8.0:
                    fine=_samples(video_path,tight_lo,tight_hi,ref,mode,sample_fps=1.0)
                    chosen=_proven_peak(fine)
                    if chosen is not None:
                        action='FACE_IDENTITY_RESCUED_DENSE_VERIFIED'
            if chosen is None:
                raise RuntimeError(f"{rec['path'].name}: FACE_ANCHOR_UNCONFIRMED; no repeated high-confidence face matches inside {lo:.1f}-{hi:.1f}")'''
    return replace_once(s,old,new,"FACE_DENSE_RETRY")

def patch_audio(s):
    old='''        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            r = rec.recognize(target, against)'''
    new='''        # Fail with actionable input evidence before Audalign/SciPy reshapes
        # a zero-length signal. Never fabricate an audio alignment candidate.
        for _rg_audio_path in (target,against):
            _rg_path=Path(_rg_audio_path)
            if not _rg_path.is_file() or _rg_path.stat().st_size<=44:
                raise RuntimeError("RG_AUDALIGN_EMPTY_OR_MISSING_AUDIO: "+str(_rg_path))
            try:
                with wave.open(str(_rg_path),"rb") as _rg_audio:
                    _rg_frames=_rg_audio.getnframes()
                    _rg_rate=_rg_audio.getframerate()
                    if _rg_frames < _rg_rate:
                        raise RuntimeError("RG_AUDALIGN_AUDIO_TOO_SHORT: "+str(_rg_path))
            except wave.Error:
                # Audalign accepts other decodable formats: do not mislabel
                # valid MP3/FLAC as invalid WAV.
                pass
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                r = rec.recognize(target, against)
        except ValueError as _rg_corr_exc:
            if "cannot reshape array of size 0" in str(_rg_corr_exc):
                raise RuntimeError("RG_AUDALIGN_EMPTY_DECODE: check truncated/incorrect source audio or disjoint offset for "+target+" against "+against) from _rg_corr_exc
            raise'''
    return replace_once(s,old,new,"AUDALIGN_INPUT_CHECK")

def patch_ui_table(s):
    old="    current=current_dialogues(stream,mains)\n    report=dict(table or {})"
    new='''    # A single revision-only main (e.g. 891_R2.xml) is not dialogue 2.
    # Accept its identity only from a matching current-run manifest; never
    # treat unknown names or duplicate entries as a valid dialogue.
    revision_one=(len(mains)==1 and re.fullmatch(
        r'RG_EDITED_'+re.escape(str(stream))+r'_R[1-9]\d*\.xml',
        ntpath.basename(str(mains[0]).replace('/', '\\\\')),re.I))
    if revision_one:
        app=Path(mains[0]).resolve().parent.parent
        manifest=app/f'RG_EDITED_{stream}_MULTI_DIALOGUE.json'
        md=json.loads(manifest.read_text(encoding='utf-8-sig'))
        rows=md.get('outputs') or []
        expected=Path(str(rows[0].get('premiere_xml') or '')).resolve() if len(rows)==1 else None
        if not (str(md.get('stream'))==str(stream)
                and str(md.get('status')) in ('QA_FAILED','DIALOGUES_COMPLETE')
                and int(md.get('dialogue_count') or 0)==1
                and len(rows)==1 and int(rows[0].get('index') or 0)==1
                and Path(mains[0]).resolve()==expected
                and expected.is_file() and expected.stat().st_size>0):
            raise ValueError('Revision-only single main not proven by current manifest')
        current=[{'id':1,'name':expected.name}]
    else:
        current=current_dialogues(stream,mains)
    report=dict(table or {})'''
    return replace_once(s,old,new,"REVISION_SINGLE_UI_QA")

PATCHES={
    "rg_studio_postrun.py":patch_postrun,
    "rg_xml_verify_v51.py":patch_xml_verify,
    "rg_face_anchor_guard_v1.py":patch_face,
    "rg_audalign_worker.py":patch_audio,
    "rg_qa_current_result.py":patch_ui_table,
}

def stage(source_dir:Path,destination:Path):
    source_dir=Path(source_dir)
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    hashes={}
    for name in FILES:
        original=(source_dir/name).read_text(encoding="utf-8")
        updated=PATCHES[name](original)
        ast.parse(updated,filename=name)
        p=destination/name
        p.write_text(updated,encoding="utf-8")
        hashes[name]={"source_sha256":hashlib.sha256(original.encode()).hexdigest(),
                      "candidate_sha256":hashlib.sha256(updated.encode()).hexdigest()}
    report={"version":PATCH_VERSION,"stage":"NOT_INSTALLED","source_dir":str(source_dir),
            "candidate_dir":str(destination),"files":hashes,
            "manual_review_required_for_unconfirmed_faces":True,
            "real_xml_source_overlap_still_blocks":True,
            "908_missing_screenshots_not_synthesized":True,
            "915_audio_alignment_not_fabricated":True}
    (destination/"RG_REPAIR_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report

if __name__=="__main__":
    import argparse
    a=argparse.ArgumentParser()
    a.add_argument("--source",required=True)
    a.add_argument("--destination",required=True)
    args=a.parse_args()
    print(json.dumps(stage(Path(args.source),Path(args.destination)),ensure_ascii=False))
