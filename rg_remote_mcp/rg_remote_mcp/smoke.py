from __future__ import annotations

import asyncio
import json
import os

from mcp import Client


EXPECTED = ("youtube", "telegram", "auto_edit")


async def main() -> None:
    url = os.getenv("RG_REMOTE_MCP_URL", "http://127.0.0.1:8765/mcp")

    async with Client(url) as client:
        health = await client.call_tool("health", {})
        if health.is_error:
            raise SystemExit(f"MCP health failed: {health.content}")

        payload = health.structured_content or {}
        contours = payload.get("contours") or {}
        missing = set(EXPECTED) - set(contours)
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

        listings = {}
        for contour in EXPECTED:
            tool = f"{contour}_fs_list"
            result = await client.call_tool(tool, {"relative": ""})
            if result.is_error:
                raise SystemExit(
                    f"{tool} failed: {result.content}"
                )
            structured = result.structured_content or {}
            listings[contour] = {
                "tool": tool,
                "ok": True,
                "items": len(structured.get("result") or structured.get("items") or []),
            }

        print("RG_NAS_MCP_PROTOCOL_PASS")
        print("CONTOURS_PASS youtube telegram auto_edit")
        print(json.dumps(
            {
                "health": payload,
                "root_listings": listings,
            },
            ensure_ascii=False,
            indent=2,
        ))


if __name__ == "__main__":
    asyncio.run(main())
