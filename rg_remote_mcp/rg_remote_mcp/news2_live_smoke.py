"""Read-only live News 2.0 MCP smoke. Never polls or sends to Telegram."""
from __future__ import annotations
import asyncio
import json
import os
from mcp import Client

def unpack(result):
    if result.is_error:
        raise RuntimeError(str(result.content))
    value = result.structured_content
    if isinstance(value, dict):
        return value.get("result", value)
    for item in result.content or []:
        text = getattr(item, "text", "")
        if text:
            obj = json.loads(text)
            return obj.get("result", obj) if isinstance(obj, dict) else obj
    raise RuntimeError("No MCP response")

async def main():
    url = os.getenv("RG_REMOTE_MCP_URL", "http://127.0.0.1:8765/mcp")
    async with Client(url) as client:
        tools = await client.list_tools()
        names = {x.name for x in tools}
        expected = {"telegram_news2_status", "telegram_news2_publish_dry_run"}
        if not expected.issubset(names):
            raise RuntimeError("Missing MCP tools: " + str(sorted(expected - names)))
        results = {}
        for name in sorted(expected):
            result = unpack(await client.call_tool(name, {}))
            results[name] = result
            entries = result.values() if name.endswith("_status") and isinstance(result, dict) else (result,)
            for entry in entries:
                if isinstance(entry, dict) and int(entry.get("exit_code", 1)) != 0:
                    raise RuntimeError(name + " failed: " + str(entry.get("stderr", ""))[:2000])
        print("NEWS2_READ_ONLY_MCP_PASS")
        print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
