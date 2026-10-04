from __future__ import annotations

import asyncio
import json
import os

from mcp import Client


REQUIRED_DEPLOY = {
    "cloudflare-video-moderation",
    "cloudflare-alerts",
    "cloudflare-content-hub",
    "cloudflare-admin-control",
}


def _payload(result):
    structured = result.structured_content or {}
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    if structured:
        return structured
    for item in result.content or []:
        value = getattr(item, "text", "")
        if not value:
            continue
        try:
            parsed = json.loads(value)
        except Exception:
            continue
        if isinstance(parsed, dict) and "result" in parsed:
            return parsed["result"]
        return parsed
    return {}


async def main() -> None:
    url = os.getenv("RG_REMOTE_MCP_URL", "http://127.0.0.1:8765/mcp")
    async with Client(url) as client:
        health = await client.call_tool("health", {})
        if health.is_error:
            raise SystemExit(f"MCP health failed: {health.content}")
        health_payload = _payload(health)
        telegram = (health_payload.get("contours") or {}).get("telegram") or {}
        if telegram.get("status") != "ok":
            raise SystemExit(
                "Telegram contour health failed: "
                + json.dumps(telegram, ensure_ascii=False)
            )

        root = await client.call_tool("telegram_fs_list", {"relative": ""})
        if root.is_error:
            raise SystemExit(f"telegram_fs_list root failed: {root.content}")

        deploy = await client.call_tool("telegram_fs_list", {"relative": "deploy"})
        if deploy.is_error:
            raise SystemExit(f"telegram_fs_list deploy failed: {deploy.content}")
        payload = _payload(deploy)
        items = payload if isinstance(payload, list) else payload.get("items", [])
        names = {
            str(item.get("name") or "")
            for item in items
            if isinstance(item, dict)
        }
        missing = REQUIRED_DEPLOY - names
        if missing:
            raise SystemExit(
                "Telegram production mounts missing: "
                + json.dumps(sorted(missing), ensure_ascii=False)
            )

        print("RG_NAS_MCP_TELEGRAM_PASS")
        print("TELEGRAM_ONLY_SCOPE_PASS")
        print("TELEGRAM_STACK_PASS video alerts content admin-control")


if __name__ == "__main__":
    asyncio.run(main())
