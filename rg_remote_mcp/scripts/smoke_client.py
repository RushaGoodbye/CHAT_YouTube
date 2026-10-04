from __future__ import annotations

import asyncio
import json
import os

from mcp import Client


async def main() -> None:
    url = os.getenv("RG_REMOTE_MCP_URL", "http://127.0.0.1:8765/mcp")
    async with Client(url) as client:
        result = await client.call_tool("health", {})
        if result.is_error:
            raise SystemExit(f"MCP health failed: {result.content}")
        print("RG_REMOTE_MCP_PASS")
        print(json.dumps(result.structured_content, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
