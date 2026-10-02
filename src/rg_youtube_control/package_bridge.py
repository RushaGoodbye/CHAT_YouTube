from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def _video_id(value: str) -> str:
    text = str(value or "").strip()
    if not VIDEO_ID_RE.fullmatch(text):
        raise ValueError("Некоректний video_id.")
    return text


def _base_url(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text.startswith(("http://", "https://")):
        raise ValueError("Некоректна адреса Package Bridge.")
    return text


def bridge_health(base_url: str, timeout: float = 3.0) -> dict[str, Any]:
    url = f"{_base_url(base_url)}/health"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "RG-YouTube-Control"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_package(
    base_url: str,
    video_id: str,
    timeout: float = 5.0,
) -> dict[str, Any] | None:
    clean_id = _video_id(video_id)
    url = f"{_base_url(base_url)}/packages/{clean_id}.json"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "RG-YouTube-Control"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not isinstance(payload, dict):
        raise ValueError("Package Bridge повернув некоректний пакет.")
    return payload


def _put(
    url: str,
    body: bytes,
    content_type: str,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "User-Agent": "RG-YouTube-Control",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def upload_transcript(
    base_url: str,
    video_id: str,
    srt: str,
    metadata: dict[str, Any],
    timeout: float = 8.0,
) -> None:
    clean_id = _video_id(video_id)
    base = _base_url(base_url)
    srt_body = str(srt or "").encode("utf-8")
    if not srt_body:
        raise ValueError("Порожній транскрипт.")
    meta_body = json.dumps(
        metadata,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    _put(
        f"{base}/transcripts/{clean_id}.srt",
        srt_body,
        "application/x-subrip; charset=utf-8",
        timeout,
    )
    _put(
        f"{base}/transcripts/{clean_id}.json",
        meta_body,
        "application/json; charset=utf-8",
        timeout,
    )