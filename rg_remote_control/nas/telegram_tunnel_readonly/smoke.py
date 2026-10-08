"""Fail-closed MCP contract test. Execute inside the running reader container."""
import asyncio
from fastmcp import Client

EXPECTED = {
    "telegram_system_status",
    "telegram_scheduler_status",
    "telegram_moderation_status",
    "telegram_publication_alert_status",
}

async def main():
    async with Client("http://127.0.0.1:18767/mcp") as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        if names != EXPECTED:
            raise SystemExit(f"REFUSED tool set: {sorted(names)} != {sorted(EXPECTED)}")
        result = await client.call_tool("telegram_system_status", {})
        if result.is_error:
            raise SystemExit("REFUSED: read-only status tool failed")
        print("READONLY_TELEGRAM_MCP_SMOKE: PASS")
        print("Allowed tools:", ", ".join(sorted(names)))

if __name__ == "__main__":
    asyncio.run(main())
