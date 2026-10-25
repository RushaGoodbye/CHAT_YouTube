#!/usr/bin/env python3
"""Read-only RG Auto Edit Studio external dependency compatibility probe.

No installs, model downloads, network calls, or edits to production media.
Runs from GitHub Actions on AlexPC. The actual F: runtime is inspected via its
own interpreter rather than the runner's unrelated Python environment.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

STUDIO = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
RUNTIME = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
PACKAGES = {
    "opencv-python": "image processing",
    "opencv-python-headless": "headless OpenCV alternative",
    "scenedetect": "independent scene-boundary evidence",
    "silero-vad": "speech/silence boundaries",
    "faster-whisper": "ASR backend",
    "whisperx": "word alignment, diarization adjunct",
    "pyannote-audio": "speaker diarization",
    "mediapipe": "face landmark/detection evidence",
    "sam2": "prompt-based moving-object segmentation",
    "torch": "CUDA inference runtime",
    "torchvision": "video/image runtime companion",
    "torchaudio": "audio runtime companion",
    "onnxruntime": "isolated CPU inference",
    "onnxruntime-gpu": "isolated GPU inference",
    "numpy": "core numeric ABI",
}
PY_SNIPPET = """
import json,sys
from importlib import metadata
names=json.loads(sys.argv[1])
out={}
for name in names:
    try:out[name]=metadata.version(name)
    except metadata.PackageNotFoundError:out[name]=None
    except Exception as exc:out[name]={"error":type(exc).__name__}
print(json.dumps({"python":sys.version.split()[0],"packages":out},sort_keys=True))
"""

def run(command, timeout=15):
    try:
        p=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",errors="replace",
                         timeout=timeout,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        return {"status":"OK" if p.returncode==0 else "ERROR","exit":p.returncode,
                "stdout":p.stdout[:3500],"stderr":p.stderr[:600]}
    except subprocess.TimeoutExpired:
        return {"status":"TIMEOUT"}
    except (OSError,ValueError) as e:
        return {"status":"UNAVAILABLE","error":type(e).__name__}

def probe():
    result={"schema":"RG_AUTO_EDIT_FOSS_COMPAT_AUDIT_V1","read_only":True,
            "installation_allowed":False,"model_downloads_allowed":False,
            "runtime":str(RUNTIME),"studio_exists":STUDIO.is_dir(),
            "runtime_exists":RUNTIME.is_file()}
    if not result["studio_exists"] or not result["runtime_exists"]:
        result["status"]="MISSING_RUNTIME"
        return result
    result["packages"]=run([str(RUNTIME),"-I","-c",PY_SNIPPET,json.dumps(list(PACKAGES))],timeout=20)
    ffprobe=shutil.which("ffprobe")
    ffmpeg=shutil.which("ffmpeg")
    result["ffprobe"]=run([ffprobe,"-version"]) if ffprobe else {"status":"NOT_ON_PATH"}
    result["ffmpeg"]=run([ffmpeg,"-version"]) if ffmpeg else {"status":"NOT_ON_PATH"}
    result["studio_ffprobe_exists"]=(STUDIO/"tools"/"ffprobe.exe").is_file()
    result["gpu"]=run(["nvidia-smi","--query-gpu=name,memory.total,driver_version","--format=csv,noheader"],timeout=10)
    result["status"]="PASS" if result["packages"].get("status")=="OK" else "REVIEW"
    return result

if __name__=="__main__":
    print("RG_FOSS_COMPAT|"+json.dumps(probe(),ensure_ascii=False),flush=True)
