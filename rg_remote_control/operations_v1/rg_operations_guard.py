from __future__ import annotations

import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import time
from pathlib import Path

VERSION = "RG_OPERATIONS_GUARD_V1"
APP = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNTIME = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
NAS_BACKUPS = Path(r"\\AlexLosServer\RG_AUTO_EDIT\BACKUPS")
NAS_AGENT = Path(r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC")
NAS_DETECTOR = Path(r"\\AlexLosServer\RG_AUTO_EDIT\DISASTER_RECOVERY\CIGARETTE_DETECTOR_V1")


def _read(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return {} if default is None else default


def _atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cigarette_paths() -> dict:
    manifest_path = DATA / "cigarette_detector_v1.json"
    manifest = _read(manifest_path, {})
    return {
        "manifest_path": manifest_path,
        "manifest": manifest,
        "model": Path(manifest.get("model") or DATA / "models" / "cigarette_blur" / "yolov8s-worldv2.pt"),
        "site": Path(manifest.get("worker_site") or DATA / "workers" / "cigarette_blur" / "site"),
        "worker": APP / "rg_cigarette_detector_worker.py",
        "module": APP / "rg_cigarette_blur.py",
    }


def mirror_cigarette_detector_to_nas() -> dict:
    p = cigarette_paths()
    NAS_DETECTOR.mkdir(parents=True, exist_ok=True)
    copied = []
    for key in ("manifest_path", "model", "worker", "module"):
        src = Path(p[key])
        if not src.is_file():
            raise RuntimeError(f"Cigarette recovery source missing: {src}")
        dst = NAS_DETECTOR / src.name
        shutil.copy2(src, dst)
        copied.append({"name": src.name, "size": dst.stat().st_size, "sha256": _sha256(dst)})
    site = Path(p["site"])
    if not (site / "ultralytics" / "__init__.py").is_file():
        raise RuntimeError("Cigarette isolated worker site is incomplete")
    site_dst = NAS_DETECTOR / "site"
    if site_dst.exists():
        shutil.rmtree(site_dst)
    shutil.copytree(site, site_dst)
    marker = {
        "schema": "RG_CIGARETTE_DETECTOR_RECOVERY_V1",
        "created_at": time.time(),
        "source_site": str(site),
        "site_backup": str(site_dst),
        "files": copied,
        "model": str(Path(p["model"])),
        "worker_site": str(site),
    }
    _atomic(NAS_DETECTOR / "RECOVERY_MANIFEST.json", marker)
    return {"passed": True, "path": str(NAS_DETECTOR), "files": copied, "site": str(site_dst)}


def ensure_cigarette_detector(restore: bool = True, verify_cuda: bool = True) -> dict:
    p = cigarette_paths()
    restored = []
    mapping = [
        (Path(p["manifest_path"]), NAS_DETECTOR / "cigarette_detector_v1.json"),
        (Path(p["model"]), NAS_DETECTOR / Path(p["model"]).name),
        (Path(p["worker"]), NAS_DETECTOR / "rg_cigarette_detector_worker.py"),
        (Path(p["module"]), NAS_DETECTOR / "rg_cigarette_blur.py"),
    ]
    if restore:
        for local, backup in mapping:
            if not local.is_file() and backup.is_file():
                local.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, local)
                restored.append(str(local))
        site = Path(p["site"])
        site_backup = NAS_DETECTOR / "site"
        if not (site / "ultralytics" / "__init__.py").is_file() and (site_backup / "ultralytics" / "__init__.py").is_file():
            if site.exists():
                shutil.rmtree(site)
            site.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(site_backup, site)
            restored.append(str(site))

    p = cigarette_paths()
    manifest = _read(Path(p["manifest_path"]), {})
    checks = {
        "manifest_ready": manifest.get("status") == "READY",
        "manifest_cuda": manifest.get("cuda") is True,
        "model": Path(p["model"]).is_file(),
        "worker": Path(p["worker"]).is_file(),
        "module": Path(p["module"]).is_file(),
        "worker_site": (Path(p["site"]) / "ultralytics" / "__init__.py").is_file(),
        "runtime": RUNTIME.is_file(),
    }
    detail = {}
    if verify_cuda and all(checks.values()):
        code = r"""
import json,os,sys
from pathlib import Path
site=Path(sys.argv[1]); app=Path(sys.argv[2])
sys.path.insert(0,str(site));sys.path.insert(1,str(app))
import torch,ultralytics
print(json.dumps({"cuda":bool(torch.cuda.is_available()),"device":torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,"ultralytics":ultralytics.__version__}))
"""
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(p["site"]) + os.pathsep + str(APP)
        cp = subprocess.run(
            [str(RUNTIME), "-X", "utf8", "-c", code, str(p["site"]), str(APP)],
            cwd=str(APP), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        try:
            detail = json.loads((cp.stdout or "").strip().splitlines()[-1])
        except Exception:
            detail = {"cuda": False, "stdout": (cp.stdout or "")[-2000:], "stderr": (cp.stderr or "")[-2000:]}
        checks["cuda_runtime"] = bool(detail.get("cuda"))
    passed = all(checks.values())
    return {"passed": passed, "checks": checks, "restored": restored, "runtime": detail, "paths": {k: str(v) for k, v in p.items() if k != "manifest"}}


def summarize_cigarette_qas(outputs) -> dict:
    rows = []
    for value in outputs or []:
        x = Path(value)
        if not x.is_file() or x.suffix.lower() != ".xml":
            continue
        q = x.with_name(x.stem + "_CIGARETTE_BLUR_QA.json")
        d = _read(q, {}) if q.is_file() else {}
        cov = d.get("coverage_qa") or {}
        rows.append({
            "xml": x.name,
            "qa": str(q),
            "passed": bool(d.get("passed")),
            "raw": int(d.get("raw_detection_count") or 0),
            "tracks": int(d.get("confirmed_track_count") or 0),
            "overlays": int(d.get("overlay_count") or 0),
            "coverage": float(cov.get("coverage_ratio") if cov.get("coverage_ratio") is not None else (1.0 if d else 0.0)),
            "missing_frames": int(cov.get("missing_frames") or 0),
            "policy": d.get("policy"),
        })
    passed = bool(rows) and all(r["passed"] and r["coverage"] >= 0.999999 and r["missing_frames"] == 0 for r in rows)
    raw = sum(r["raw"] for r in rows)
    tracks = sum(r["tracks"] for r in rows)
    overlays = sum(r["overlays"] for r in rows)
    coverage = min([r["coverage"] for r in rows] or [0.0])
    if passed:
        display = f"PASS • перевірено={len(rows)} • знайдено={tracks} • blur={overlays} • coverage={coverage*100:.0f}%"
    else:
        bad = [r["xml"] for r in rows if not r["passed"] or r["coverage"] < 0.999999 or r["missing_frames"]]
        display = "ЕКСПОРТ ЗАБЛОКОВАНО - перевірте сигарету" + ((" • " + ",".join(bad[:5])) if bad else " • QA відсутній")
    return {"passed": passed, "files_checked": len(rows), "raw": raw, "tracks": tracks, "overlays": overlays, "coverage_ratio": coverage, "rows": rows, "display": display}


def cigarette_fail_closed_message(detail="") -> str:
    tail = str(detail or "")
    if "UNCONFIRMED_CIGARETTE_DETECTIONS" in tail:
        return "ЕКСПОРТ ЗАБЛОКОВАНО - перевірте сигарету. Є підозрілий об'єкт, але стабільний трек не підтверджено."
    if "CIGARETTE" in tail.upper():
        return "ЕКСПОРТ ЗАБЛОКОВАНО - перевірте сигарету. Обов'язковий cigarette blur не пройшов QA."
    return "Помилка production backend"


def cleanup_operational_artifacts(retain_days: int = 7) -> dict:
    cutoff = time.time() - max(1, int(retain_days)) * 86400
    removed = []
    roots = [
        NAS_AGENT / "auto_edit" / "requests",
        NAS_AGENT / "auto_edit" / "results",
        NAS_AGENT / "auto_edit" / "errors",
        NAS_AGENT / "auto_edit" / "processing",
        DATA / "temp",
        DATA / "tmp",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for p in root.iterdir():
                try:
                    if not p.is_file() or p.stat().st_mtime >= cutoff:
                        continue
                    p.unlink()
                    removed.append(str(p))
                except Exception:
                    pass
        except Exception:
            pass
    # Preserve the real 886 GOLDEN fixture; remove only old throwaway validation folders.
    val = DATA / "validation"
    if val.is_dir():
        for p in val.iterdir():
            try:
                if p.name == "cigarette_blur_real_886":
                    continue
                if p.is_dir() and p.stat().st_mtime < cutoff and p.name.lower().startswith(("tmp","probe","cigarette_probe","smoke_")):
                    shutil.rmtree(p)
                    removed.append(str(p))
            except Exception:
                pass
    return {"removed_count": len(removed), "removed": removed[:200], "retain_days": retain_days}


def _compile_core() -> list:
    names = [
        "rg_studio_ui.py", "rg_studio_postrun.py", "rg_auto_edit_one_button.py",
        "rg_cigarette_blur.py", "rg_cigarette_detector_worker.py",
        "rg_final_release_gate.py", "rg_final_timeline_audit.py",
        "rg_premiere_native_xml.py", "VALIDATE_PREMIERE_XML.py",
        "rg_studio_update_worker.py", "rg_operations_guard.py",
    ]
    out = []
    for name in names:
        p = APP / name
        if not p.is_file():
            out.append({"name": name, "ok": False, "detail": "missing"})
            continue
        try:
            py_compile.compile(str(p), doraise=True)
            out.append({"name": name, "ok": True, "detail": "compile"})
        except Exception as exc:
            out.append({"name": name, "ok": False, "detail": repr(exc)})
    return out


def regression_gate(require_real_fixture: bool = True) -> dict:
    checks = []
    compiled = _compile_core()
    checks.extend({"name": "compile:" + x["name"], "ok": x["ok"], "detail": x["detail"]} for x in compiled)

    det = ensure_cigarette_detector(restore=True, verify_cuda=True)
    checks.append({"name": "cigarette_detector", "ok": det["passed"], "detail": json.dumps(det.get("checks"), ensure_ascii=False)})

    cfg = _read(APP / "rg_auto_edit_config.json", {})
    cig = cfg.get("cigarette_blur") or {}
    checks.append({"name": "cigarette_mandatory", "ok": cig.get("enabled") is True and cig.get("mandatory") is True and cig.get("fail_closed") is True, "detail": cig.get("policy")})
    checks.append({"name": "whole_frame_forbidden", "ok": cig.get("whole_frame_blur_forbidden") is True, "detail": cig.get("whole_frame_blur_forbidden")})
    checks.append({"name": "source_audio_untouched", "ok": cig.get("source_audio_untouched") is True, "detail": cig.get("source_audio_untouched")})

    stable = _read(DATA / "CURRENT_STABLE.json", {})
    checks.append({"name": "golden_020202", "ok": stable.get("version") == "0.20.20.2" and stable.get("golden") is True and stable.get("verified") is True, "detail": stable.get("version")})

    fixture_path = DATA / "validation" / "cigarette_blur_real_886" / "REAL_886_CIGARETTE_E2E_QA.json"
    fixture = _read(fixture_path, {}) if fixture_path.is_file() else {}
    fixture_ok = bool(
        fixture.get("overall_passed") and fixture.get("status") == "TRACKED"
        and (fixture.get("xml_qa") or {}).get("passed")
        and float(((fixture.get("xml_qa") or {}).get("coverage_qa") or {}).get("coverage_ratio") or 0.0) >= 0.999999
        and int(((fixture.get("xml_qa") or {}).get("coverage_qa") or {}).get("missing_frames") or 0) == 0
    )
    checks.append({"name": "real_cigarette_e2e_886", "ok": fixture_ok if require_real_fixture else True, "detail": str(fixture_path)})

    passed = all(x["ok"] for x in checks)
    report = {
        "schema": "RG_OPERATIONS_REGRESSION_V1",
        "version": VERSION,
        "passed": passed,
        "checks": checks,
        "detector": det,
        "time": time.time(),
    }
    out = DATA / "selftests" / f"OPERATIONS_{int(time.time())}.json"
    _atomic(out, report)
    report["report"] = str(out)
    if not passed:
        failed = [x["name"] for x in checks if not x["ok"]]
        raise RuntimeError("OPERATIONS REGRESSION GATE FAILED: " + ",".join(failed))
    return report


def pre_update_gate() -> dict:
    report = regression_gate(require_real_fixture=True)
    report["purpose"] = "PRE_UPDATE"
    return report


def control_health() -> dict:
    status_path = NAS_AGENT / "status" / "alexpc_agent.json"
    status = _read(status_path, {}) if status_path.is_file() else {}
    local_agent = Path(r"C:\RG_AGENT\alexpc_agent.py")
    bundle_agent = NAS_AGENT / "BUNDLE" / "rg_remote_control" / "alexpc_agent.py"
    local_task = Path(r"C:\RG_AGENT\bundle_cache\rg_remote_control\task_runner.py")
    bundle_task = NAS_AGENT / "BUNDLE" / "rg_remote_control" / "task_runner.py"
    pairs = {}
    for name, a, b in (
        ("agent", local_agent, bundle_agent),
        ("task_runner", local_task, bundle_task),
    ):
        pairs[name] = {
            "local": str(a), "bundle": str(b),
            "local_exists": a.is_file(), "bundle_exists": b.is_file(),
            "same": bool(a.is_file() and b.is_file() and a.stat().st_size == b.stat().st_size and _sha256(a) == _sha256(b)),
        }
    return {
        "passed": status.get("state") in {"ready", "busy"} and all(v["same"] for v in pairs.values()),
        "agent_status": status,
        "sync": pairs,
        "github_required": status.get("github_required"),
    }


def write_operations_status(extra=None) -> dict:
    state = {
        "schema": "RG_AUTO_EDIT_OPERATIONS_V1",
        "version": VERSION,
        "updated_at": time.time(),
        "control": control_health(),
        "detector": ensure_cigarette_detector(restore=True, verify_cuda=False),
        "stable": _read(DATA / "CURRENT_STABLE.json", {}),
        "powershell_normal_operations_required": False,
    }
    if extra:
        state["extra"] = extra
    _atomic(DATA / "OPERATIONS_STATUS.json", state)
    return state


def submit_nas_action(action: str, args=None, timeout_seconds: int = 3600) -> dict:
    if not action.startswith(("auto_edit_", "inspect_auto_edit_", "apply_auto_edit_", "verify_auto_edit_", "audit_auto_edit_", "finalize_auto_edit_", "start_auto_edit_", "launch_auto_edit_")):
        raise ValueError("Action is outside auto_edit contour")
    rid = "studio-" + str(int(time.time() * 1000))
    req = NAS_AGENT / "auto_edit" / "requests" / (rid + ".json")
    payload = {"request_id": rid, "action": action, "args": dict(args or {}), "timeout_seconds": int(timeout_seconds)}
    _atomic(req, payload)
    return {"submitted": True, "request_id": rid, "path": str(req)}
