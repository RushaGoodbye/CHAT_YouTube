"""Read-only release inventory. Never imports or executes installed Studio code."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

APP = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
SHADOW = DATA / "oss_shadow"
NAS = Path(r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_files():
    files = list(APP.glob("*.py"))
    files += list(APP.glob("rg_auto_edit_config.json"))
    files += list(APP.glob("*.xml"))
    files += list((APP / "886").glob("*.xml"))
    files += list((APP / "886").glob("*HOLD*.json"))
    return {str(p): digest(p) for p in sorted(set(files)) if p.is_file()}


def command(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"exit_code": p.returncode, "output": p.stdout[-8000:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": type(e).__name__}


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    before = protected_files()
    hold = APP / "886" / "RG_EDITED_886_5.SEMANTIC_HOLD.json"
    q = json.loads(hold.read_text(encoding="utf-8-sig")) if hold.is_file() else {}
    publish = [APP / "RG_EDITED_886_5.xml", APP / "886" / "RG_EDITED_886_5.xml"]
    valid_hold = all(q.get(k) == v for k, v in (
        ("schema", "RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1"),
        ("do_not_publish", True), ("primary_xml_withheld", True),
        ("delivered_xml_withheld", True))) and not any(p.exists() for p in publish)
    assets = []
    for folder in sorted(SHADOW.iterdir()) if SHADOW.is_dir() else []:
        if not folder.is_dir():
            continue
        rows = []
        for path in sorted(folder.rglob("*")):
            rel = path.relative_to(folder)
            if len(rel.parts) > 3 or not path.is_file():
                continue
            if path.suffix.lower() not in (".json", ".zip", ".mp4", ".onnx", ".pt", ".npz"):
                continue
            if any(k in str(rel).lower() for k in ("token", "credential", "secret", "oauth")):
                continue
            rows.append({"file": str(path), "bytes": path.stat().st_size})
        assets.append({"folder": folder.name, "files": rows[:160]})
    runtimes = []
    for py in sorted((DATA / "oss_envs").glob("*/Scripts/python.exe")):
        probe = command([str(py), "-I", "-c", "import sys,importlib.util,json;print(json.dumps({'python':sys.version,'modules':{n:bool(importlib.util.find_spec(n)) for n in ['cv2','torch','sam2','transformers','numpy']}}))"])
        runtimes.append({"path": str(py), "probe": probe})
    source_archive = out / "installed_source_readonly.zip"
    with zipfile.ZipFile(source_archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(APP.glob("*.py")):
            if not any(k in p.name.lower() for k in ("token", "credential", "secret", "oauth")):
                z.write(p, "app/" + p.name)
        for p in sorted((APP / "tests").glob("*.py")):
            z.write(p, "app/tests/" + p.name)
    sample_archive = out / "existing_shadow_samples.zip"
    names = {
        "892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4",
        "RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip",
        "RG_892_YUNET_MOUTH_SHADOW_RESULT_V1.zip",
    }
    selected = []
    total = 0
    with zipfile.ZipFile(sample_archive, "w", zipfile.ZIP_DEFLATED) as z:
        for group in assets:
            for row in group["files"]:
                p = Path(row["file"])
                negative = ("886" in str(p.relative_to(SHADOW)) and p.suffix.lower() in (".zip", ".mp4")
                            and p.stat().st_size < 60 * 1024 ** 2)
                if p.name not in names and not negative:
                    continue
                if total + p.stat().st_size > 160 * 1024 ** 2:
                    continue
                z.write(p, str(p.relative_to(SHADOW)))
                total += p.stat().st_size
                selected.append({"path": str(p.relative_to(SHADOW)), "sha256": digest(p)})
    report = {
        "schema": "RG_SMOKING_RELEASE_READONLY_INVENTORY_V1",
        "commit": os.environ.get("GITHUB_SHA"), "machine": os.environ.get("COMPUTERNAME"),
        "app_exists": APP.is_dir(), "data_exists": DATA.is_dir(),
        "quarantine_886_5_valid": valid_hold,
        "quarantine_886_5_sha256": digest(hold) if hold.is_file() else None,
        "protected_files_before": before, "assets": assets, "runtimes": runtimes,
        "gpu": command(["nvidia-smi", "--query-gpu=name,memory.free", "--format=csv,noheader"]),
        "nas_accessible": NAS.is_dir(),
        "selected_samples": selected, "source_archive_sha256": digest(source_archive),
        "studio_changed": before != protected_files(),
        "release_allowed": False,
    }
    (out / "inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("machine", "app_exists", "data_exists", "quarantine_886_5_valid", "nas_accessible", "studio_changed", "release_allowed")}), flush=True)
    if not valid_hold or report["studio_changed"]:
        raise SystemExit("Release inventory safety guard failed")


if __name__ == "__main__":
    main()
