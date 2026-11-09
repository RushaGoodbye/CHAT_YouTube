"""Read-only acceptance of the November 9 RG repair on live AlexPC.
Never write to active app, run montage, alter queue, or mark files ready.
"""
from pathlib import Path
import json, sys, os, re, hashlib, xml.etree.ElementTree as ET
from urllib.parse import unquote

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
sys.path.insert(0,str(APP))
from rg_studio_postrun import _primary_outputs
from rg_xml_verify_v51 import _src_span, _audio_paths

def line(*items):
    print("RGACCEPT|"+"|".join(str(x) for x in items),flush=True)

def load_json(path):
    try: return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError,ValueError) as exc:
        line("JSON_ERROR",path.name,repr(exc));return None

def audit(stream):
    directory=APP/str(stream)
    manifest_path=APP/f"RG_EDITED_{stream}_MULTI_DIALOGUE.json"
    manifest=load_json(manifest_path)
    if not isinstance(manifest,dict):
        line("STREAM",stream,"MANIFEST_MISSING");return
    outputs=_primary_outputs(directory,[],str(stream))
    line("STREAM",stream,"MANIFEST_STATUS",manifest.get("status"),"DIALOGUES",manifest.get("dialogue_count"),
         "CURRENT_XML_COUNT",len(outputs))
    expected=int(manifest.get("dialogue_count") or 0)
    line("STREAM",stream,"COUNT_CONSISTENT",len(outputs)==expected and expected>0)
    ranges=[]
    for x in outputs:
        if not x.is_file():
            line("FILE_MISSING",stream,x.name);continue
        try:
            tree=ET.parse(x)
            span=_src_span(x)
            urls=_audio_paths(x)
            line("XML",stream,x.name,"SIZE",x.stat().st_size,"VIDEO_SPAN_FRAMES",span,
                 "AUDIO_REFS",len(urls),"PARSE_PASS",True)
            if span[0] is not None and span[1] is not None:
                ranges.append((x.name,int(span[0]),int(span[1])))
            bad=[a for a in urls if 'DIALOGUE_AUDIO' in a.upper() or 'NORMALIZED' in a.upper()]
            line("XML",stream,x.name,"ORIGINAL_AUDIO_REF_OK",not bool(bad))
        except Exception as exc:
            line("XML",stream,x.name,"PARSE_FAIL",repr(exc))
    for earlier,later in zip(ranges,ranges[1:]):
        if later[1]<earlier[2]:
            line("OVERLAP",stream,earlier[0],later[0],"FRAMES",earlier[2]-later[1])
    # Postrun full QA includes sidecar gates, not only XML parsing.
    for row in (manifest.get("outputs") or []):
        n=Path(str(row.get("premiere_xml") or row.get("xml") or "")).stem
        for suffix in ("_FINAL_RELEASE_GATE.json","_FINAL_TIMELINE_AUDIT.json","_CIGARETTE_BLUR_QA.json"):
            candidate=APP/(n+suffix)
            local=directory/(n+suffix)
            p=local if local.is_file() else candidate
            if p.is_file():
                data=load_json(p)
                if isinstance(data,dict):
                    line("SIDECAR",stream,p.name,"PASS",data.get("passed"),"STATUS",data.get("status"),
                         "CHECKS",len(data.get("checks") or []),
                         "FAILURES",str(data.get("failures") or [])[:300])
            else:
                line("SIDECAR_MISSING",stream,n+suffix)
    # Any old failure should remain visible, never reinterpret structural PASS as release approval.
    for p in (APP/(f"RG_EDITED_{stream}_POSTRUN_QA.json"),directory/"RG_POSTRUN_QA.json"):
        if p.is_file():
            data=load_json(p)
            if isinstance(data,dict):
                line("EXISTING_QA",stream,p.name,"PASS",data.get("passed"),
                    "FAILED_CHECKS",[(e.get("name"),str(e.get("detail",""))[:150]) for e in data.get("checks",[]) if not e.get("ok")][:14])

def audio_check_915():
    import rg_embedded_audio_source_v1 as audio
    # This calls ffprobe only. No audio extraction.
    v=Path(r"\\AlexLosServer\Work\WORK\RUSHA GOODBYE\Раша GOODBYE\ГОТОВО\ЗАПИСИ СТРИМОВ\RushaGoodbye - Live\RushaGoodbye - Live\915.mp4")
    a=Path(r"\\AlexLosServer\Work\WORK\RUSHA GOODBYE\Раша GOODBYE\ГОТОВО\ЗАПИСИ СТРИМОВ\RushaGoodbye - Live\sound\915-1.mp3")
    b=Path(r"\\AlexLosServer\Work\WORK\RUSHA GOODBYE\Раша GOODBYE\ГОТОВО\ЗАПИСИ СТРИМОВ\RushaGoodbye - Live\sound\915-2.mp3")
    if not all(p.is_file() for p in (v,a,b)):
        line("915","FILES_MISSING",[(p.name,p.is_file()) for p in (v,a,b)]);return
    pi=audio._probe(v)
    dur=audio._duration(pi)
    d1=audio._duration(audio._probe(a));d2=audio._duration(audio._probe(b))
    evidence=audio._good_embedded(pi,dur)
    line("915","MP4_DURATION_SEC",round(dur,3),"SPLIT_DURATION_SEC",round(d1+d2,3),
         "DELTA_SEC",round(d1+d2-dur,3),"EMBEDDED_SYNC_OK",evidence)
    line("915","FALLBACK_ELIGIBLE",bool(evidence and min(d1,d2)>60 and abs(d1+d2-dur)>max(30,dur*.015)))
    log=APP/"run_manifests"/"915"/"LATEST.log"
    if log.is_file():
        error=[x for x in log.read_text(encoding="utf-8",errors="replace").splitlines() if "ValueError: cannot reshape array of size 0" in x]
        line("915","PREVIOUS_EMPTY_AUDIO_ERROR",bool(error))
    line("915","REPROCESS_REQUIRED",True)

def main():
    line("TIME",__import__("datetime").datetime.now().astimezone().isoformat())
    queue=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\studio_batch_queue.json")
    if queue.is_file():
        j=load_json(queue)
        if isinstance(j,dict):line("QUEUE","RUNNING",j.get("running"),"PAUSED",j.get("paused"))
    for stream in (891,898,904):
        try:audit(stream)
        except Exception as exc:line("STREAM_EXCEPTION",stream,repr(exc))
    try:audio_check_915()
    except Exception as exc:line("915_EXCEPTION",repr(exc))
    line("NO_PRODUCTION_FILES_MODIFIED",True)
if __name__=="__main__":main()
