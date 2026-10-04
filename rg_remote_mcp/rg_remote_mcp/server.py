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
