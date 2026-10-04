from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(os.getenv("RG_WORKER_ROOT", "/workspace")).resolve()
CONTOUR = os.getenv("RG_WORKER_CONTOUR", "unknown")
ALLOWED = frozenset(
    item.strip().casefold()
    for item in os.getenv("RG_WORKER_COMMANDS", "").split(",")
    if item.strip()
)
MAX_READ = int(os.getenv("RG_REMOTE_MAX_READ_BYTES", str(1024 * 1024)))
MAX_WRITE = int(os.getenv("RG_REMOTE_MAX_WRITE_BYTES", str(1024 * 1024)))


def _path(relative: str = "") -> Path:
    candidate = (ROOT / str(relative or "")).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("Path escapes worker root") from exc
    return candidate


def _json_error(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "contour": CONTOUR,
        "root": str(ROOT),
        "allowed_commands": sorted(ALLOWED),
    })


async def fs_list(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        path = _path(body.get("relative", ""))
        if not path.is_dir():
            raise ValueError("Not a directory")
        items = []
        for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
            stat = item.stat()
            items.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else None,
                "mtime_ns": stat.st_mtime_ns,
            })
        return JSONResponse({"ok": True, "items": items})
    except Exception as exc:
        return _json_error(exc)


async def fs_read(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        path = _path(body["relative"])
        if not path.is_file():
            raise ValueError("Not a file")
        if path.stat().st_size > MAX_READ:
            raise ValueError("File exceeds read limit")
        return JSONResponse({
            "ok": True,
            "content": path.read_text(encoding="utf-8", errors="replace"),
        })
    except Exception as exc:
        return _json_error(exc)


async def fs_write(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        raw = str(body.get("content", "")).encode("utf-8")
        if len(raw) > MAX_WRITE:
            raise ValueError("Payload exceeds write limit")
        path = _path(body["relative"])
        if bool(body.get("create_parents", True)):
            path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".rgworker.tmp")
        temp.write_bytes(raw)
        os.replace(temp, path)
        return JSONResponse({"ok": True, "bytes": len(raw)})
    except Exception as exc:
        return _json_error(exc)


async def fs_mkdir(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        path = _path(body["relative"])
        path.mkdir(parents=True, exist_ok=True)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return _json_error(exc)


async def fs_copy(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        src = _path(body["source"])
        dst = _path(body["destination"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                raise ValueError("Destination already exists")
            shutil.copytree(src, dst)
        elif src.is_file():
            shutil.copy2(src, dst)
        else:
            raise ValueError("Source does not exist")
        return JSONResponse({"ok": True})
    except Exception as exc:
        return _json_error(exc)


async def command_run(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        argv = [str(item) for item in body.get("argv", [])]
        if not argv:
            raise ValueError("argv must not be empty")
        command = Path(argv[0]).name.casefold()
        if command not in ALLOWED:
            raise ValueError(f"Command is not allow-listed: {command}")
        cwd = _path(body.get("cwd_relative", ""))
        timeout = max(1, min(int(body.get("timeout_seconds", 120)), 900))
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError("Command timed out")
        return JSONResponse({
            "ok": True,
            "exit_code": int(proc.returncode or 0),
            "stdout": stdout.decode("utf-8", errors="replace")[-200000:],
            "stderr": stderr.decode("utf-8", errors="replace")[-200000:],
        })
    except Exception as exc:
        return _json_error(exc)


app = Starlette(routes=[
    Route("/health", health, methods=["GET"]),
    Route("/fs/list", fs_list, methods=["POST"]),
    Route("/fs/read", fs_read, methods=["POST"]),
    Route("/fs/write", fs_write, methods=["POST"]),
    Route("/fs/mkdir", fs_mkdir, methods=["POST"]),
    Route("/fs/copy", fs_copy, methods=["POST"]),
    Route("/command", command_run, methods=["POST"]),
])


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8780)


if __name__ == "__main__":
    main()
