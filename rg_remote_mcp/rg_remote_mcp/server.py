from __future__ import annotations

from mcp.server import MCPServer

from .hubclient import WORKERS, worker_get, worker_post

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
