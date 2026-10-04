from __future__ import annotations

import asyncio
import json
import os

from mcp import Client


EXPECTED = ("youtube", "telegram", "auto_edit")


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

        payload = _payload(health)
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
            structured = _payload(result)
            if isinstance(structured, list):
                item_count = len(structured)
            elif isinstance(structured, dict):
                items = structured.get("items") or structured.get("result") or []
                item_count = len(items) if isinstance(items, list) else 0
            else:
                item_count = 0
            listings[contour] = {
                "tool": tool,
                "ok": True,
                "items": item_count,
            }

        telegram_deploy = await client.call_tool("telegram_fs_list", {"relative": "deploy"})
        if telegram_deploy.is_error:
            raise SystemExit(f"telegram_fs_list deploy failed: {telegram_deploy.content}")
        telegram_payload = _payload(telegram_deploy)
        telegram_items = telegram_payload if isinstance(telegram_payload, list) else telegram_payload.get("items", [])
        telegram_names = {
            str(item.get("name") or "")
            for item in telegram_items
            if isinstance(item, dict)
        }
        required_telegram = {
            "cloudflare-video-moderation",
            "cloudflare-alerts",
            "cloudflare-content-hub",
            "cloudflare-admin-control",
        }
        missing_telegram = required_telegram - telegram_names
        if missing_telegram:
            raise SystemExit(
                "Telegram contour missing production mounts: "
                + json.dumps(sorted(missing_telegram), ensure_ascii=False)
            )

        print("RG_NAS_MCP_PROTOCOL_PASS")
        print("CONTOURS_PASS youtube telegram auto_edit")
        print("TELEGRAM_STACK_PASS video alerts content admin-control")
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
