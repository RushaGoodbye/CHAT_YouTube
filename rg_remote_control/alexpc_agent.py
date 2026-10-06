from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
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


def sync_bundle_if_changed() -> dict:
    nas_manifest = NAS_ROOT / "BUNDLE" / "bundle_manifest.json"
    local_manifest = LOCAL_STATE / "bundle_manifest.json"
    try:
        nas_text = nas_manifest.read_text(encoding="utf-8", errors="replace") if nas_manifest.is_file() else ""
    except Exception:
        nas_text = ""
    try:
        local_text = local_manifest.read_text(encoding="utf-8", errors="replace") if local_manifest.is_file() else ""
    except Exception:
        local_text = ""

    cache_ready = (LOCAL_CACHE / "rg_remote_control" / "task_runner.py").is_file()
    if nas_text and nas_text == local_text and cache_ready:
        return {"ok": True, "changed": False}

    result = sync_bundle()
    if result.get("ok") and nas_text:
        LOCAL_STATE.mkdir(parents=True, exist_ok=True)
        local_manifest.write_text(nas_text, encoding="utf-8")
    result["changed"] = True
    return result


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

    sync_bundle_if_changed()
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



def _processes_json(filter_script: str) -> str:
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            filter_script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    return (proc.stdout or "").strip()


def ensure_youtube_gui() -> dict:
    target = Path.home() / "CHAT_YouTube-main"
    run_app = target / "run_app.py"
    pythonw = target / ".venv" / "Scripts" / "pythonw.exe"
    if not run_app.is_file() or not pythonw.is_file():
        return {
            "ok": False,
            "reason": "local_gui_runtime_missing",
            "run_app": str(run_app),
            "pythonw": str(pythonw),
        }

    probe_cmd = (
        "$p=Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') "
        "-and $_.CommandLine -like '*CHAT_YouTube-main*run_app.py*' }; "
        "$p | Select-Object ProcessId,Name,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    before = _processes_json(probe_cmd)
    started = False
    if not before or before in {"null", "[]"}:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(target / "src")
        env.pop("RUNNER_TRACKING_ID", None)
        flags = 0
        if os.name == "nt":
            flags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        subprocess.Popen(
            [str(pythonw), str(run_app)],
            cwd=str(target),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        started = True
        time.sleep(3)
    after = _processes_json(probe_cmd)
    return {
        "ok": bool(after and after not in {"null", "[]"}),
        "started": started,
        "processes": after,
    }


def ensure_ollama() -> dict:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/tags",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [
            str(item.get("name") or item.get("model") or "")
            for item in payload.get("models", [])
            if isinstance(item, dict)
        ]
        ready = any(x.startswith("qwen3:8b") for x in models)
        return {"ok": True, "started": False, "qwen3_8b": ready}
    except Exception:
        pass

    candidates = [
        shutil.which("ollama"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "ollama.exe"),
    ]
    exe = next((x for x in candidates if x and Path(x).is_file()), None)
    if not exe:
        return {"ok": False, "reason": "ollama_executable_missing"}

    flags = 0
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    subprocess.Popen(
        [exe, "serve"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    for _ in range(12):
        time.sleep(1)
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/tags",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models = [
                str(item.get("name") or item.get("model") or "")
                for item in payload.get("models", [])
                if isinstance(item, dict)
            ]
            return {
                "ok": True,
                "started": True,
                "qwen3_8b": any(x.startswith("qwen3:8b") for x in models),
            }
        except Exception:
            continue
    return {"ok": False, "started": True, "reason": "ollama_start_timeout"}


def ensure_dirs() -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    LOCAL_STATE.mkdir(parents=True, exist_ok=True)
    if NAS_ROOT.exists():
        for contour in CONTOURS:
            base = NAS_ROOT / contour
            for name in ("requests", "processing", "results", "errors"):
                (base / name).mkdir(parents=True, exist_ok=True)
        (NAS_ROOT / "status").mkdir(parents=True, exist_ok=True)


def write_status(
    state: str,
    active: dict | None = None,
    services: dict | None = None,
) -> None:
    payload = {
        "schema": "RG_ALEXPC_AGENT_V1",
        "computer": os.environ.get("COMPUTERNAME", ""),
        "pid": os.getpid(),
        "state": state,
        "active": active,
        "updated_at": now_iso(),
        "poll_seconds": POLL_SECONDS,
        "github_required": False,
        "services": services or {},
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
    sync_bundle_if_changed()
    last_heartbeat = 0.0
    write_status("ready")

    while True:
        try:
            ensure_dirs()
            if time.time() - last_service_check >= 60:
                services = {
                    "youtube_gui": ensure_youtube_gui(),
                    "ollama": ensure_ollama(),
                }
                last_service_check = time.time()
            if time.time() - last_heartbeat >= HEARTBEAT_SECONDS:
                write_status("ready", services=services)
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
                        write_status("busy", active, services=services)
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
                            write_status("ready", services=services)
                        break
                    if did_work:
                        break
            if not did_work:
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            write_status("stopped", services=services)
            return
        except Exception as exc:
            atomic_json(
                LOCAL_STATE / "last_error.json",
                {"at": now_iso(), "error": repr(exc), "traceback": traceback.format_exc()[-20000:]},
            )
            write_status("degraded", services=services)
            time.sleep(10)


if __name__ == "__main__":
    _mutex = acquire_single_instance()
    if _mutex is False:
        raise SystemExit(0)
    run_loop()
