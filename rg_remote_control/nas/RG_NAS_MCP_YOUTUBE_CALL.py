from __future__ import annotations

import asyncio
import json
import sys

from mcp import Client


def _content(result):
    items = []
    for item in result.content or []:
        entry = {"type": getattr(item, "type", None)}
        text = getattr(item, "text", None)
        if text is not None:
            entry["text"] = text
        items.append(entry)
    return items


async def main(path: str) -> None:
    with open(path, "r", encoding="utf-8") as fh:
        request = json.load(fh)

    request_id = str(request.get("request_id") or "")
    tool = str(request.get("tool") or "").strip()
    tool_args = request.get("tool_args") or {}

    if not request_id:
        raise SystemExit("missing request_id")
    if not tool.startswith("youtube_"):
        raise SystemExit("only youtube_* tools are allowed")
    if not isinstance(tool_args, dict):
        raise SystemExit("tool_args must be an object")

    async with Client("http://127.0.0.1:8765/mcp") as client:
        result = await client.call_tool(tool, tool_args)

    payload = {
        "request_id": request_id,
        "tool": tool,
        "is_error": bool(result.is_error),
        "structured_content": result.structured_content,
        "content": _content(result),
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: RG_NAS_MCP_YOUTUBE_CALL.py <request.json>")
    asyncio.run(main(sys.argv[1]))
