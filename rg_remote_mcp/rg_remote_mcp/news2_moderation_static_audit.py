"""Fail-closed static review of installed News2 moderation source over MCP.
Reads source only. No token, Telegram API, SQLite access or execution.
"""
from __future__ import annotations
import asyncio
import ast
import json
import os
from mcp import Client

FILES = ["rg_moderation.py", "rg_v36.py", "rg_v35.py"]
TARGETS = {"send_one", "claim_next", "poll_once", "process_callback", "config", "main", "poll", "publish"}
SECRET_NAMES = ("TOKEN", "SECRET", "PASSWORD", "CHAT_ID")

def unwrap(result):
    if result.is_error:
        raise RuntimeError("MCP read failed")
    obj = result.structured_content
    if isinstance(obj, dict):
        obj = obj.get("result", obj)
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return obj.get("content", "")
    for item in result.content or []:
        value = getattr(item, "text", "")
        try:
            obj = json.loads(value)
            if isinstance(obj, str):
                return obj
        except ValueError:
            pass
    raise RuntimeError("No readable source")

def extract(src, filename):
    tree = ast.parse(src, filename=filename)
    lines = src.splitlines()
    extracted = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in TARGETS:
            # Report statement and call structure, not source strings or credentials.
            calls = []
            for x in ast.walk(node):
                if isinstance(x, ast.Call):
                    target = x.func
                    if isinstance(target, ast.Name):
                        calls.append(target.id)
                    elif isinstance(target, ast.Attribute):
                        calls.append(target.attr)
            extracted[node.name] = {
                "lines": [node.lineno, node.end_lineno],
                "calls": sorted(set(calls)),
                "has_try": any(isinstance(x, ast.Try) for x in ast.walk(node)),
                "has_transaction": any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr in ("commit", "rollback") for x in ast.walk(node)),
            }
    return {"file": filename, "length_lines": len(lines), "functions": extracted,
            "telegram_api_references": {k: src.count(k) for k in ("getUpdates", "sendPhoto", "answerCallbackQuery")},
            "risk_notes": [
                "Static structure is not proof of idempotence or exclusive getUpdates ownership",
                "Do not enable moderation polling or photo delivery on this report alone",
            ]}

async def main():
    out = {}
    async with Client(os.getenv("RG_REMOTE_MCP_URL", "http://127.0.0.1:8765/mcp")) as client:
        for filename in FILES:
            src = unwrap(await client.call_tool("telegram_fs_read_text", {"relative": "telegram_news_2/" + filename}))
            out[filename] = extract(src, filename)
    print("NEWS2_MODERATION_STATIC_AUDIT_PASS")
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
