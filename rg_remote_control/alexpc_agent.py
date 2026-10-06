from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

NAS_ROOT = Path(r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC")
LOCAL_ROOT = Path(r"C:\RG_AGENT")
LOCAL_CACHE = LOCAL_ROOT / "bundle_cache"
LOCAL_STATE = LOCAL_ROOT / "state"
HEARTBEAT_SECONDS = 10
POLL_SECONDS = 3

CONTOURS = ("youtube", "telegram", "auto_edit")


def acquire_single_instance():
    if os.name != "nt":
        return None
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Global\\RG_ALEXPC_AGENT_V1")
    if not handle:
        raise RuntimeError("Could not create RG AlexPC Agent mutex")
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return False
    return handle


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def sync_bundle() -> dict:
    source = NAS_ROOT / "BUNDLE"
    if not source.is_dir():
        return {"ok": False, "reason": "nas_bundle_missing"}
    LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
    copied = 0
    for rel in (
        "rg_remote_control",
        "src",
    ):
        src = source / rel
        dst = LOCAL_CACHE / rel
        if not src.exists():
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        copied += 1
    for name in ("run_app.py", "pyproject.toml", "requirements.txt"):
        src = source / name
        if src.is_file():
            shutil.copy2(src, LOCAL_CACHE / name)
            copied += 1
    return {"ok": copied > 0, "copied": copied}


def allowed(contour: str, action: str) -> bool:
    if contour == "youtube":
        return action.startswith("youtube_")
    if contour == "telegram":
        return action.startswith("telegram_")
    if contour == "auto_edit":
        prefixes = (
            "auto_edit_", "inspect_auto_edit_", "apply_auto_edit_",
            "build_auto_edit_", "start_auto_edit_", "launch_auto_edit_",
            "verify_auto_edit_", "audit_auto_edit_", "finalize_auto_edit_",
            "locate_auto_edit_", "search_auto_edit_",
        )
        return action.startswith(prefixes) or action in {
            "install_rg_resilience", "probe_rg_resilience", "repair_rg_resilience"
        }
    return False


def resolve_handler(contour: str, action: str) -> Path:
    control = LOCAL_CACHE / "rg_remote_control"
    if contour == "youtube" and action.startswith("youtube_local_"):
        return control / "youtube_local_tool.py"
    if contour == "auto_edit" and action in {
        "install_rg_resilience", "probe_rg_resilience", "repair_rg_resilience"
    }:
        return control / "resilience_tool.py"
    return control / "task_runner.py"


def process_request(path: Path, contour: str) -> dict:
    request = json.loads(path.read_text(encoding="utf-8-sig"))
    request_id = str(request.get("request_id") or path.stem)
    action = str(request.get("action") or "").strip()
    args = request.get("args") or {}
    if not allowed(contour, action):
        raise RuntimeError(f"Action not allowed for {contour}: {action}")
    if not isinstance(args, dict):
        raise RuntimeError("args must be an object")

    handler = resolve_handler(contour, action)
    if not handler.is_file():
        sync_bundle()
    if not handler.is_file():
        raise RuntimeError(f"Handler missing: {handler}")

    task = {
        "target": "alexpc",
        "contour": contour,
        "action": action,
        "args": args,
    }
    with tempfile.TemporaryDirectory(prefix="rg_agent_") as tmp:
        task_path = Path(tmp) / "task.json"
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(handler), str(task_path)],
            cwd=str(LOCAL_CACHE),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(request.get("timeout_seconds") or 3600),
        )
    return {
        "request_id": request_id,
        "contour": contour,
        "action": action,
        "finished_at": now_iso(),
        "exit_code": proc.returncode,
        "ok": proc.returncode == 0,
        "stdout": (proc.stdout or "")[-50000:],
        "stderr": (proc.stderr or "")[-20000:],
    }


def ensure_dirs() -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    LOCAL_STATE.mkdir(parents=True, exist_ok=True)
    if NAS_ROOT.exists():
        for contour in CONTOURS:
            base = NAS_ROOT / contour
            for name in ("requests", "processing", "results", "errors"):
                (base / name).mkdir(parents=True, exist_ok=True)
        (NAS_ROOT / "status").mkdir(parents=True, exist_ok=True)


def write_status(state: str, active: dict | None = None) -> None:
    payload = {
        "schema": "RG_ALEXPC_AGENT_V1",
        "computer": os.environ.get("COMPUTERNAME", ""),
        "pid": os.getpid(),
        "state": state,
        "active": active,
        "updated_at": now_iso(),
        "poll_seconds": POLL_SECONDS,
        "github_required": False,
    }
    atomic_json(LOCAL_STATE / "agent_status.json", payload)
    try:
        atomic_json(NAS_ROOT / "status" / "alexpc_agent.json", payload)
    except Exception:
        pass


def claim(path: Path, processing_dir: Path) -> Path | None:
    target = processing_dir / path.name
    try:
        os.replace(path, target)
        return target
    except Exception:
        return None


def run_loop() -> None:
    ensure_dirs()
    sync_bundle()
    last_heartbeat = 0.0
    write_status("ready")

    while True:
        try:
            ensure_dirs()
            if time.time() - last_heartbeat >= HEARTBEAT_SECONDS:
                write_status("ready")
                last_heartbeat = time.time()

            did_work = False
            if NAS_ROOT.exists():
                for contour in CONTOURS:
                    base = NAS_ROOT / contour
                    requests = base / "requests"
                    processing = base / "processing"
                    results = base / "results"
                    errors = base / "errors"
                    for req in sorted(requests.glob("*.json")):
                        claimed = claim(req, processing)
                        if not claimed:
                            continue
                        did_work = True
                        active = {"contour": contour, "request": claimed.name}
                        write_status("busy", active)
                        try:
                            result = process_request(claimed, contour)
                            atomic_json(results / claimed.name, result)
                            if not result.get("ok"):
                                atomic_json(errors / claimed.name, result)
                        except Exception as exc:
                            payload = {
                                "request_id": claimed.stem,
                                "contour": contour,
                                "ok": False,
                                "finished_at": now_iso(),
                                "error": repr(exc),
                                "traceback": traceback.format_exc()[-20000:],
                            }
                            atomic_json(errors / claimed.name, payload)
                        finally:
                            try:
                                claimed.unlink()
                            except Exception:
                                pass
                            write_status("ready")
                        break
                    if did_work:
                        break
            if not did_work:
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            write_status("stopped")
            return
        except Exception as exc:
            atomic_json(
                LOCAL_STATE / "last_error.json",
                {"at": now_iso(), "error": repr(exc), "traceback": traceback.format_exc()[-20000:]},
            )
            write_status("degraded")
            time.sleep(10)


if __name__ == "__main__":
    _mutex = acquire_single_instance()
    if _mutex is False:
        raise SystemExit(0)
    run_loop()
