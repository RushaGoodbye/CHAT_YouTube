from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_NAS_ROOT = Path(r"\\AlexLosServer\docker")
LOCAL_APP = Path.home() / "CHAT_YouTube-main"
LOCAL_TOOL = LOCAL_APP / "rg_remote_control" / "youtube_local_tool.py"
LOCAL_PYTHON = LOCAL_APP / ".venv" / "Scripts" / "python.exe"

ALLOWED_PREFIX = "youtube_local_"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


class SingleInstance:
    def __init__(self, name: str) -> None:
        self.handle = None
        self.name = name

    def __enter__(self):
        if os.name != "nt":
            return self
        import ctypes

        kernel32 = ctypes.windll.kernel32
        self.handle = kernel32.CreateMutexW(None, False, self.name)
        if not self.handle:
            raise RuntimeError("Could not create agent mutex")
        if kernel32.GetLastError() == 183:
            raise SystemExit(0)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle and os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self.handle)


class YouTubeNasAgent:
    def __init__(self) -> None:
        root = Path(os.environ.get("RG_NAS_ROOT") or str(DEFAULT_NAS_ROOT))
        self.root = root
        self.queue = root / "RG_NAS_MCP" / "YOUTUBE_HOST_CALLS"
        self.requests = self.queue / "requests"
        self.processing = self.queue / "processing"
        self.results = self.queue / "results"
        self.errors = self.queue / "errors"
        self.state = self.queue / "state"
        self.heartbeat = self.state / "alexpc.json"
        self.poll_seconds = max(2, int(os.environ.get("RG_YOUTUBE_AGENT_POLL_SECONDS", "5")))
        self.last_request = ""
        self.last_error = ""

    def ensure_dirs(self) -> None:
        for path in (
            self.requests,
            self.processing,
            self.results,
            self.errors,
            self.state,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def status(self, status: str = "online", **extra) -> None:
        payload = {
            "schema": "RG_YOUTUBE_AGENT_V1",
            "status": status,
            "updated_at": utc_now(),
            "computer": os.environ.get("COMPUTERNAME", ""),
            "pid": os.getpid(),
            "nas_root": str(self.root),
            "queue_root": str(self.queue),
            "local_app": str(LOCAL_APP),
            "local_tool_exists": LOCAL_TOOL.is_file(),
            "local_python_exists": LOCAL_PYTHON.is_file(),
            "last_request": self.last_request,
            "last_error": self.last_error,
            **extra,
        }
        atomic_json(self.heartbeat, payload)

    def claim(self, request: Path) -> Path | None:
        claimed = self.processing / request.name
        try:
            os.replace(request, claimed)
            return claimed
        except (FileNotFoundError, PermissionError, OSError):
            return None

    def execute(self, claimed: Path) -> None:
        started = time.time()
        request_id = claimed.stem
        try:
            payload = json.loads(claimed.read_text(encoding="utf-8-sig"))
            request_id = str(payload.get("request_id") or request_id).strip()
            action = str(payload.get("action") or "").strip()
            args = payload.get("args") or {}
            if not request_id:
                raise RuntimeError("missing request_id")
            if not action.startswith(ALLOWED_PREFIX):
                raise RuntimeError("only youtube_local_* actions are allowed")
            if not isinstance(args, dict):
                raise RuntimeError("args must be an object")
            if not LOCAL_TOOL.is_file():
                raise RuntimeError(f"local YouTube tool missing: {LOCAL_TOOL}")
            if not LOCAL_PYTHON.is_file():
                raise RuntimeError(f"local Python runtime missing: {LOCAL_PYTHON}")

            task_path = self.processing / f"{request_id}.task.json"
            atomic_json(
                task_path,
                {
                    "target": "alexpc",
                    "contour": "youtube",
                    "action": action,
                    "args": args,
                },
            )
            proc = subprocess.run(
                [str(LOCAL_PYTHON), str(LOCAL_TOOL), str(task_path)],
                cwd=str(LOCAL_APP),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(60, int(payload.get("timeout_seconds") or 3600)),
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            parsed = None
            if stdout.strip():
                try:
                    parsed = json.loads(stdout)
                except Exception:
                    parsed = None
            result = {
                "schema": "RG_YOUTUBE_HOST_RESULT_V1",
                "request_id": request_id,
                "action": action,
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "started_at": datetime.fromtimestamp(
                    time.time() - (time.time() - started), timezone.utc
                ).isoformat(),
                "finished_at": utc_now(),
                "elapsed_seconds": round(time.time() - started, 2),
                "result": parsed,
                "stdout": stdout[-12000:],
                "stderr": stderr[-12000:],
            }
            atomic_json(self.results / f"{request_id}.json", result)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"youtube_local_tool exited {proc.returncode}: {stderr[-2000:]}"
                )
            self.last_request = request_id
            self.last_error = ""
        except Exception as exc:
            self.last_request = request_id
            self.last_error = repr(exc)
            atomic_json(
                self.errors / f"{request_id}.json",
                {
                    "schema": "RG_YOUTUBE_HOST_ERROR_V1",
                    "request_id": request_id,
                    "ok": False,
                    "error": repr(exc),
                    "finished_at": utc_now(),
                },
            )
        finally:
            try:
                claimed.unlink()
            except Exception:
                pass
            task_path = self.processing / f"{request_id}.task.json"
            try:
                task_path.unlink()
            except Exception:
                pass
            self.status()

    def run_forever(self) -> None:
        while True:
            try:
                self.ensure_dirs()
                self.status()
                for request in sorted(self.requests.glob("*.json")):
                    claimed = self.claim(request)
                    if claimed:
                        self.execute(claimed)
                        break
            except Exception as exc:
                self.last_error = repr(exc)
                try:
                    self.status(status="degraded")
                except Exception:
                    pass
            time.sleep(self.poll_seconds)


def main() -> int:
    with SingleInstance(r"Global\RG_YOUTUBE_NAS_AGENT_V1"):
        YouTubeNasAgent().run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
