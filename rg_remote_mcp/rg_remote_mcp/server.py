from __future__ import annotations

from mcp.server import MCPServer

from .hubclient import WORKERS, worker_get, worker_post

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

ALEXPC_ROOT = Path(os.getenv("RG_ALEXPC_ROOT", "/alexpc"))


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


async def _alexpc_submit(
    contour: str,
    action: str,
    args: dict | None = None,
    timeout_seconds: int = 180,
    wait: bool = True,
) -> dict:
    contour = str(contour).strip().casefold()
    if contour not in {"youtube", "telegram", "auto_edit"}:
        raise ValueError("invalid contour")
    action = str(action or "").strip()
    if not action:
        raise ValueError("action is required")
    timeout_seconds = max(5, min(int(timeout_seconds), 3600))

    request_id = uuid.uuid4().hex
    base = ALEXPC_ROOT / contour
    request = {
        "request_id": request_id,
        "contour": contour,
        "action": action,
        "args": dict(args or {}),
        "created_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "timeout_seconds": timeout_seconds,
    }
    _atomic_json(base / "requests" / f"{request_id}.json", request)

    queued = {
        "request_id": request_id,
        "contour": contour,
        "action": action,
        "queued": True,
        "github_required": False,
    }
    if not wait:
        return queued

    result_path = base / "results" / f"{request_id}.json"
    error_path = base / "errors" / f"{request_id}.json"
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        if result_path.is_file():
            return {**queued, "result": _read_json(result_path)}
        if error_path.is_file():
            return {**queued, "error": _read_json(error_path)}
        await asyncio.sleep(1)

    return {
        **queued,
        "timeout": True,
        "timeout_seconds": timeout_seconds,
    }


async def _alexpc_status(contour: str) -> dict:
    status = _read_json(ALEXPC_ROOT / "status" / "alexpc_agent.json")
    base = ALEXPC_ROOT / contour
    counts = {}
    for name in ("requests", "processing", "results", "errors"):
        folder = base / name
        try:
            counts[name] = sum(1 for p in folder.glob("*.json"))
        except Exception:
            counts[name] = 0
    updated = str(status.get("updated_at") or "")
    age = None
    if updated:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            age = None
    return {
        "contour": contour,
        "agent": status,
        "agent_online": age is not None and age < 45,
        "age_seconds": round(age, 1) if age is not None else None,
        "queue": counts,
        "github_required": False,
    }


mcp = MCPServer("RG NAS MCP Hub")


@mcp.tool()
async def health() -> dict:
    """Return hub and worker health for all isolated contours."""
    contours = {}
    for name in ("youtube", "telegram", "auto_edit"):
        try:
            worker = await worker_get(name, "/health")
            contours[name] = {
                "status": "ok",
                "worker": worker,
            }
        except Exception as exc:
            contours[name] = {
                "status": "error",
                "error": str(exc),
            }
    return {
        "status": (
            "ok"
            if all(item["status"] == "ok" for item in contours.values())
            else "degraded"
        ),
        "server": "RG NAS MCP Hub",
        "contours": contours,
    }


def _register_contour(name: str) -> None:
    async def fs_list(relative: str = "") -> list[dict]:
        result = await worker_post(name, "/fs/list", {"relative": relative})
        return list(result.get("items") or [])

    async def fs_read_text(relative: str) -> str:
        result = await worker_post(name, "/fs/read", {"relative": relative})
        return str(result.get("content") or "")

    async def fs_write_text(
        relative: str,
        content: str,
        create_parents: bool = True,
    ) -> dict:
        result = await worker_post(
            name,
            "/fs/write",
            {
                "relative": relative,
                "content": content,
                "create_parents": create_parents,
            },
        )
        return {
            "contour": name,
            "bytes": int(result.get("bytes") or 0),
        }

    async def fs_make_dir(relative: str) -> dict:
        await worker_post(name, "/fs/mkdir", {"relative": relative})
        return {"contour": name, "created": relative}

    async def fs_copy(source: str, destination: str) -> dict:
        await worker_post(
            name,
            "/fs/copy",
            {"source": source, "destination": destination},
        )
        return {
            "contour": name,
            "source": source,
            "destination": destination,
        }

    async def command_run(
        argv: list[str],
        cwd_relative: str = "",
        timeout_seconds: int = 120,
    ) -> dict:
        result = await worker_post(
            name,
            "/command",
            {
                "argv": argv,
                "cwd_relative": cwd_relative,
                "timeout_seconds": timeout_seconds,
            },
        )
        return {
            "contour": name,
            "exit_code": int(result.get("exit_code") or 0),
            "stdout": str(result.get("stdout") or ""),
            "stderr": str(result.get("stderr") or ""),
        }

    fs_list.__name__ = f"{name}_fs_list"
    fs_read_text.__name__ = f"{name}_fs_read_text"
    fs_write_text.__name__ = f"{name}_fs_write_text"
    fs_make_dir.__name__ = f"{name}_fs_make_dir"
    fs_copy.__name__ = f"{name}_fs_copy"
    command_run.__name__ = f"{name}_command_run"

    mcp.tool(name=f"{name}_fs_list")(fs_list)
    mcp.tool(name=f"{name}_fs_read_text")(fs_read_text)
    mcp.tool(name=f"{name}_fs_write_text")(fs_write_text)
    mcp.tool(name=f"{name}_fs_make_dir")(fs_make_dir)
    mcp.tool(name=f"{name}_fs_copy")(fs_copy)
    mcp.tool(name=f"{name}_command_run")(command_run)


for _contour_name in WORKERS:
    _register_contour(_contour_name)


async def _auto_read_json(relative: str) -> dict:
    import json
    try:
        result = await worker_post("auto_edit", "/fs/read", {"relative": relative})
        text = str(result.get("content") or "")
        return json.loads(text) if text.strip() else {}
    except Exception:
        return {}


async def _auto_list(relative: str) -> list[dict]:
    try:
        result = await worker_post("auto_edit", "/fs/list", {"relative": relative})
        return list(result.get("items") or [])
    except Exception:
        return []


@mcp.tool(name="auto_edit_status")
async def auto_edit_status() -> dict:
    """Return canonical RG Auto Edit production status exported by Studio."""
    status = await _auto_read_json("CONTROL/STATE/PRODUCTION_STATUS.json")
    generated = float(status.get("generated_at") or 0)
    age = max(0.0, __import__("time").time() - generated) if generated else None
    return {
        "contour": "auto_edit",
        "status": status,
        "stale": age is None or age > 30,
        "age_seconds": round(age, 1) if age is not None else None,
    }


@mcp.tool(name="auto_edit_queue")
async def auto_edit_queue() -> dict:
    """Return canonical live RG Auto Edit queue. Never falls back to legacy batch state."""
    queue = await _auto_read_json("CONTROL/STATE/PRODUCTION_QUEUE.json")
    generated = float(queue.get("generated_at") or 0)
    age = max(0.0, __import__("time").time() - generated) if generated else None
    return {
        "contour": "auto_edit",
        "queue": queue,
        "stale": age is None or age > 30,
        "age_seconds": round(age, 1) if age is not None else None,
    }


@mcp.tool(name="auto_edit_run")
async def auto_edit_run(stream: str) -> dict:
    """Return latest archived run manifest and QA for one stream."""
    stream = str(stream).strip()
    if not stream.isdigit():
        raise ValueError("stream must be numeric")
    items = await _auto_list(f"RUNS/{stream}")
    dirs = sorted(
        [x.get("name") for x in items if x.get("type") == "dir" and x.get("name")],
        reverse=True,
    )
    if not dirs:
        return {"contour": "auto_edit", "stream": stream, "found": False}
    latest = dirs[0]
    base = f"RUNS/{stream}/{latest}"
    return {
        "contour": "auto_edit",
        "stream": stream,
        "found": True,
        "run": latest,
        "manifest": await _auto_read_json(f"{base}/RUN_MANIFEST.json"),
        "qa": await _auto_read_json(f"{base}/QA/RG_POSTRUN_QA.json"),
        "censor_items": await _auto_list(f"{base}/CENSOR"),
    }


@mcp.tool(name="auto_edit_qa")
async def auto_edit_qa(stream: str) -> dict:
    """Return latest RG Auto Edit QA only."""
    data = await auto_edit_run(stream)
    return {
        "contour": "auto_edit",
        "stream": str(stream),
        "found": bool(data.get("found")),
        "run": data.get("run"),
        "qa": data.get("qa") or {},
    }


@mcp.tool(name="auto_edit_batch")
async def auto_edit_batch(parts: list[str] | None = None, stream: str = "") -> dict:
    """Return several common Auto Edit status surfaces in one read-only call."""
    wanted = list(parts or ["status", "queue"])
    out = {"contour": "auto_edit"}
    if "status" in wanted:
        out["status"] = await auto_edit_status()
    if "queue" in wanted:
        out["queue"] = await auto_edit_queue()
    if "run" in wanted and stream:
        out["run"] = await auto_edit_run(stream)
    if "qa" in wanted and stream:
        out["qa"] = await auto_edit_qa(stream)
    return out


@mcp.tool(name="auto_edit_event_stream")
async def auto_edit_event_stream(limit: int = 100) -> dict:
    """Return recent Studio-published Auto Edit events if available."""
    limit = max(1, min(int(limit), 500))
    try:
        result = await worker_post(
            "auto_edit", "/fs/read", {"relative": "CONTROL/STATE/MCP_EVENTS.jsonl"}
        )
        text = str(result.get("content") or "")
    except Exception:
        text = ""
    lines = [x for x in text.splitlines() if x.strip()][-limit:]
    events = []
    import json
    for line in lines:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return {"contour": "auto_edit", "events": events, "count": len(events)}


@mcp.tool(name="auto_edit_diagnostics_snapshot")
async def auto_edit_diagnostics_snapshot(stream: str) -> dict:
    """Return read-only diagnostic inventory for one stream."""
    stream = str(stream).strip()
    if not stream.isdigit():
        raise ValueError("stream must be numeric")
    return {
        "contour": "auto_edit",
        "stream": stream,
        "diagnostics": await _auto_list(f"DIAGNOSTICS/{stream}"),
        "run": await auto_edit_run(stream),
    }




@mcp.tool(name="youtube_alexpc_task")
async def youtube_alexpc_task(
    action: str,
    args: dict | None = None,
    timeout_seconds: int = 180,
    wait: bool = True,
) -> dict:
    """Run a YouTube-contour task on AlexPC through the NAS queue, without GitHub Actions."""
    if not str(action).startswith("youtube_"):
        raise ValueError("YouTube AlexPC action must start with youtube_")
    return await _alexpc_submit("youtube", action, args, timeout_seconds, wait)


@mcp.tool(name="youtube_alexpc_status")
async def youtube_alexpc_status() -> dict:
    """Return AlexPC NAS-agent health and YouTube queue status."""
    return await _alexpc_status("youtube")


@mcp.tool(name="telegram_alexpc_task")
async def telegram_alexpc_task(
    action: str,
    args: dict | None = None,
    timeout_seconds: int = 180,
    wait: bool = True,
) -> dict:
    """Run a Telegram-contour task on AlexPC through the NAS queue, without GitHub Actions."""
    if not str(action).startswith("telegram_"):
        raise ValueError("Telegram AlexPC action must start with telegram_")
    return await _alexpc_submit("telegram", action, args, timeout_seconds, wait)


@mcp.tool(name="telegram_alexpc_status")
async def telegram_alexpc_status() -> dict:
    """Return AlexPC NAS-agent health and Telegram queue status."""
    return await _alexpc_status("telegram")


@mcp.tool(name="auto_edit_alexpc_task")
async def auto_edit_alexpc_task(
    action: str,
    args: dict | None = None,
    timeout_seconds: int = 180,
    wait: bool = True,
) -> dict:
    """Run an Auto Edit task on AlexPC through the NAS queue, without GitHub Actions."""
    return await _alexpc_submit("auto_edit", action, args, timeout_seconds, wait)


@mcp.tool(name="auto_edit_alexpc_status")
async def auto_edit_alexpc_status() -> dict:
    """Return AlexPC NAS-agent health and Auto Edit queue status."""
    return await _alexpc_status("auto_edit")


def main() -> None:
    import os

    mcp.run(
        transport="streamable-http",
        host=os.getenv("RG_REMOTE_HOST", "0.0.0.0"),
        port=int(os.getenv("RG_REMOTE_PORT", "8765")),
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
