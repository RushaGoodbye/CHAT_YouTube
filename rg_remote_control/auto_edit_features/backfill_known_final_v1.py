from __future__ import annotations
# RG backfill only the previously confirmed 2026-10-11 final compilation; no media changes.
import json, subprocess, sys
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
WORK=APP/"FINAL_COMPILATIONS"/"MIX_20261011_184220"
SELECTION=WORK/"RG_FINAL_SELECTION.json"
EXPECTED=["891-2.mp4","890-6.mp4","890-7.mp4","900-3.mp4"]

def main():
    from importlib.util import spec_from_file_location,module_from_spec
    spec=spec_from_file_location("rg_used_dialogues", APP/"rg_used_dialogues.py")
    mod=module_from_spec(spec);spec.loader.exec_module(mod)
    obj=json.loads(SELECTION.read_text(encoding="utf-8-sig"))
    paths=[Path(p) for p in obj["clips"]]
    if [p.name for p in paths]!=EXPECTED:
        raise RuntimeError("Unexpected source selection; refusing history migration")
    if not all(p.is_file() for p in paths):
        raise RuntimeError("Missing original clip")
    output=paths[0].parent/"Creat"/"891_2_890_6_890_7_900_3_FINAL_FFMPEG.mp4"
    if not output.is_file() or output.stat().st_size<1000000:
        raise RuntimeError("Previously completed MP4 not found: "+str(output))
    ffprobe=APP/"tools"/"ffprobe.exe"
    if not ffprobe.is_file():
        import shutil
        f=shutil.which("ffprobe")
        if not f: raise RuntimeError("ffprobe unavailable")
        ffprobe=Path(f)
    cmd=[str(ffprobe),"-v","error","-show_entries","stream=codec_type:format=duration","-of","json",str(output)]
    proc=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
    if proc.returncode:raise RuntimeError("ffprobe: "+proc.stderr[-500:])
    probe=json.loads(proc.stdout)
    streams={s.get("codec_type") for s in probe.get("streams",[])}
    duration=float(probe.get("format",{}).get("duration") or 0)
    if not {"video","audio"}.issubset(streams) or abs(duration-2143.333)>3:
        raise RuntimeError("Previous MP4 failed media verification")
    print("PRIOR_RENDER_CHECK: PASS")
    print("FILE:",output)
    print("DURATION:",duration)
    print("CLIPS:",",".join(EXPECTED))
    if "--apply" in sys.argv:
        count=mod.record_success(paths,output,"MIX_20261011_184220")
        print("HISTORY_BACKFILL: PASS; NEW RECORDS:",count)
        print("SOURCE_RENAMES: NONE")
    else:
        print("BACKFILL_PRECHECK: PASS; NO_CHANGES: TRUE")
if __name__=="__main__":main()
