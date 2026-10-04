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

        payload = result.structured_content or {}
        contours = payload.get("contours") or {}
        expected = {"youtube", "telegram", "auto_edit"}
        missing = expected - set(contours)
        if missing:
            raise SystemExit(f"Missing contours: {sorted(missing)}")

        failed = {
            name: value
            for name, value in contours.items()
            if (value or {}).get("status") != "ok"
        }
        if failed:
            raise SystemExit(
                "Contour health failed: "
                + json.dumps(failed, ensure_ascii=False)
            )

        print("RG_NAS_MCP_HUB_PASS")
        print("CONTOURS_PASS youtube telegram auto_edit")
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
