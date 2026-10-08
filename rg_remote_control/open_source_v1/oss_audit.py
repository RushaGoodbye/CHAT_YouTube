#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only OSS capability and license-policy audit for the RG Auto Edit contour."""
from __future__ import annotations
import argparse
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys

BASE = Path(__file__).resolve().parent
DEFAULT_APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DEFAULT_RUNTIME=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
PACKAGE_NAMES={
  "pyscenedetect":("scenedetect","scenedetect"),
  "norfair":("norfair","norfair"),
  "sam2":("sam2","sam2"),
  "groundingdino":("groundingdino","groundingdino"),
  "rfdetr":("rfdetr","rfdetr"),
  "faster-whisper":("faster-whisper","faster_whisper"),
  "whisperx":("whisperx","whisperx"),
  "silero-vad":("silero-vad","silero_vad"),
  "pyannote-audio":("pyannote.audio","pyannote.audio"),
  "supervision":("supervision","supervision"),
  "opentimelineio-fcp":("opentimelineio","opentimelineio"),
  "onnxruntime":("onnxruntime-gpu","onnxruntime"),
  "ultralytics":("ultralytics","ultralytics"),
  "pyside6":("PySide6","PySide6"),
  "psutil":("psutil","psutil"),
  "watchdog":("watchdog","watchdog"),
  "tenacity":("tenacity","tenacity"),
  "apscheduler":("APScheduler","apscheduler"),
  "pydantic":("pydantic","pydantic"),
  "loguru":("loguru","loguru"),
  "pyqtgraph":("pyqtgraph","pyqtgraph"),
}
def safe_probe(distribution, module):
    try:
        version=metadata.version(distribution)
    except metadata.PackageNotFoundError:
        version=None
    try:
        module_found=importlib.util.find_spec(module) is not None
    except (ImportError,ValueError,ModuleNotFoundError):
        module_found=False
    return {"version":version,"import_spec_present":module_found}

def report(*,catalog_path=BASE/"catalog.json", app_root=DEFAULT_APP):
    catalog=json.loads(Path(catalog_path).read_text(encoding="utf-8-sig"))
    if catalog.get("rg_nas_mcp_contour","auto_edit")!="auto_edit" or catalog.get("contour")!="auto_edit":
        raise RuntimeError("OSS registry is outside auto_edit contour")
    components=[]
    for record in catalog["components"]:
        entry={
           "id":record["id"],"decision":record["status"],
           "repository":record["repo"],"license":record["license"]
        }
        if record["id"] in PACKAGE_NAMES:
            dist,mod=PACKAGE_NAMES[record["id"]]
            entry["current_python"]=safe_probe(dist,mod)
        components.append(entry)
    app_root=Path(app_root)
    cfg=app_root/"rg_auto_edit_config.json"
    safety={"config_present":cfg.is_file(),
       "cigarette_mandatory":None,"cigarette_fail_closed":None,
       "whole_frame_blur_forbidden":None}
    if cfg.is_file():
        try:
            doc=json.loads(cfg.read_text(encoding="utf-8-sig"))
            c=doc.get("cigarette_blur") or {}
            safety.update(cigarette_mandatory=c.get("mandatory") is True,
                cigarette_fail_closed=c.get("fail_closed") is True,
                whole_frame_blur_forbidden=c.get("whole_frame_blur_forbidden") is True)
        except (OSError,ValueError):
            safety["config_read_error"]=True
    return {
       "schema":"RG_OSS_RUNTIME_AUDIT_V1",
       "contour":"auto_edit",
       "read_only":True,
       "installation_attempted":False,
       "production_modified":False,
       "python":sys.version.split()[0],
       "platform":platform.platform(),
       "runtime_expected":str(DEFAULT_RUNTIME),
       "components":components,
       "safety":safety,
       "recommended_first_pilot":"pyscenedetect",
       "known_licensing_review_required":[
           "ultralytics","cotracker","ffmpeg build flags","pyannote weights","rfdetr plus"
       ]
    }

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--catalog",type=Path,default=BASE/"catalog.json")
    parser.add_argument("--app-root",type=Path,default=DEFAULT_APP)
    args=parser.parse_args(argv)
    print(json.dumps(report(catalog_path=args.catalog,app_root=args.app_root),
                     ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
