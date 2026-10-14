"""Read-only News2 activation audit over already installed MCP. No bot API, polls, sends, or DB writes."""
from __future__ import annotations
import asyncio
import ast
import json
import os
import re
from mcp import Client

FILES = ("rg_v35.py", "rg_v36.py", "rg_v37.py", "rg_moderation.py", "rg_news.py")
BLOCKED = ("getUpdates", "sendPhoto", "sendMessage", "answerCallbackQuery")

def unpack(response):
    if response.is_error:
        return {"error": "MCP_READ_FAILED"}
    value = response.structured_content
    if isinstance(value, dict):
        return value.get("result", value)
    if isinstance(value, list):
        return value
    for item in response.content or []:
        try:
            value = json.loads(getattr(item, "text", ""))
            return value.get("result", value) if isinstance(value, dict) else value
        except (ValueError, TypeError):
            pass
    return {}

def describe(filename, source):
    tree = ast.parse(source, filename=filename)
    parser_commands = []
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("add_parser", "add_argument"):
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    parser_commands.append(arg.value)
    return {
        "present": True,
        "bytes": len(source.encode("utf-8")),
        "defined_functions": sorted(set(functions))[:100],
        "cli_keywords": sorted(set(parser_commands))[:120],
        "telegram_api_symbols": [name for name in BLOCKED if name in source],
        "has_main_guard": "__main__" in source,
        "absolute_news2_path": "/volume1/docker/RG_TELEGRAM_NEWS_2" in source,
    }

async def main():
    url = os.getenv("RG_REMOTE_MCP_URL", "http://127.0.0.1:8765/mcp")
    results = {}
    async with Client(url) as client:
        listing = unpack(await client.call_tool("telegram_fs_list", {"relative": "telegram_news_2"}))
        items = listing if isinstance(listing, list) else listing.get("items", [])
        found = {item.get("name") for item in items if isinstance(item, dict)}
        for filename in FILES:
            if filename not in found:
                results[filename] = {"present": False}
                continue
            response = unpack(await client.call_tool("telegram_fs_read_text", {"relative": "telegram_news_2/" + filename}))
            source = response if isinstance(response, str) else response.get("result") or response.get("content") if isinstance(response, dict) else ""
            if not isinstance(source, str) or not source:
                results[filename] = {"present": True, "readable": False}
                continue
            try:
                results[filename] = describe(filename, source)
            except SyntaxError as exc:
                results[filename] = {"present": True, "syntax_error": exc.msg}
    print("NEWS2_ACTIVATION_AUDIT_READ_ONLY")
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
