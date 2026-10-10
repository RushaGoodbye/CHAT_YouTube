#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only 904 launch readiness diagnosis; no studio/process/media mutations."""
import json
from pathlib import Path
import os
import re
import time

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
ROOT=Path(r"\\Desktop-v7gg0en\record")
SOUND=ROOT/"sound"
STREAM="904"

def exists(p):
    try:
        return {"exists":p.is_file(),"bytes":p.stat().st_size if p.is_file() else None}
    except Exception as exc:
        return {"exists":False,"error":str(exc)[:180]}

def nearby(root):
    try:
        results=[]
        for entry in root.iterdir():
            if entry.name.lower().startswith(STREAM.lower()):
                try: info={"name":entry.name,"bytes":entry.stat().st_size if entry.is_file() else None}
                except Exception:info={"name":entry.name}
                results.append(info)
                if len(results)>=20:break
        return {"folder_exists":root.is_dir(),"matches":results}
    except Exception as exc:
        return {"folder_exists":False,"error":str(exc)[:250]}

def ui_context():
    p=APP/"rg_studio_ui.py"
    if not p.is_file():return {"missing":True}
    lines=p.read_text(encoding="utf-8-sig",errors="replace").splitlines()
    patterns=("ПОТРІБНА ПЕРЕВІРКА","ЗАПУСТИТИ","Аудіо: файл не знайдено","Аудіо","ПЕРЕВІРИТИ ГОТОВНІСТЬ",
              "preflight","start_button","start_btn")
    hit=[]
    for i,line in enumerate(lines):
        if any(k.lower() in line.lower() for k in patterns):
            # Limiting output, but show key UI phrases and action hooks
            snippet="\n".join(f"{j+1}: {lines[j]}" for j in range(max(0,i-3),min(len(lines),i+4)))
            hit.append({"line":i+1,"snippet":snippet})
            if len(hit)>=45:break
    return {"size":p.stat().st_size,"matches":hit}

def main():
    results={
      "schema":"RG_904_LAUNCH_READONLY_PROBE_V1",
      "time_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
      "read_only":True,"stream":STREAM,
      "source_video":exists(ROOT/(STREAM+".mp4")),
      "source_audio_mp3":exists(SOUND/(STREAM+".mp3")),
      "input_video_variants":nearby(ROOT),
      "input_audio_variants":nearby(SOUND),
      "screen_photos":nearby(ROOT/"Screens"),
      "studio_ui":ui_context(),
    }
    print("RG_904_LAUNCH_READONLY_PROBE")
    print(json.dumps(results,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
