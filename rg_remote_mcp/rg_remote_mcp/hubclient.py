from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request


WORKERS = {
    "youtube": os.getenv("RG_WORKER_YOUTUBE_URL", "http://youtube-worker:8780"),
    "telegram": os.getenv("RG_WORKER_TELEGRAM_URL", "http://telegram-worker:8780"),
    "auto_edit": os.getenv("RG_WORKER_AUTO_EDIT_URL", "http://auto-edit-worker:8780"),
}


def _base(contour: str) -> str:
    key = str(contour or "").casefold()
    if key not in WORKERS:
        raise ValueError(f"Unknown contour: {contour}")
    return WORKERS[key].rstrip("/")


def _sync_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Worker HTTP {exc.code}: {body}") from exc
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "Worker request failed"))
    return result


async def worker_get(contour: str, path: str) -> dict:
    return await asyncio.to_thread(_sync_json, "GET", _base(contour) + path, None)


async def worker_post(contour: str, path: str, payload: dict) -> dict:
    return await asyncio.to_thread(_sync_json, "POST", _base(contour) + path, payload)
