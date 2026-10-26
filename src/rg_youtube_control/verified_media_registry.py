"""Explicitly verified YouTube-to-local-media bindings.

No fuzzy title association is allowed. Store user-verified associations
separately from generated SEO drafts; validate file existence on each lookup.
"""
from __future__ import annotations

import json
from pathlib import Path

from .local_media_sources import valid_video_id, MEDIA_EXTENSIONS


def get_verified_media(mapping_path: Path, video_id: str) -> Path | None:
    if not valid_video_id(video_id):
        return None
    try:
        data = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
        item = data.get(video_id)
        if not isinstance(item, dict) or item.get("verified") is not True:
            return None
        path = Path(item["path"])
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            return None
        if not path.is_file() or path.stat().st_size <= 0:
            return None
        return path
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def save_verified_media(mapping_path: Path, video_id: str, media: Path) -> None:
    """Persist an explicit user-confirmed association without guessing."""
    if not valid_video_id(video_id):
        raise ValueError("Invalid video ID")
    media = Path(media)
    if media.suffix.lower() not in MEDIA_EXTENSIONS or not media.is_file():
        raise FileNotFoundError("Selected source media is unavailable")
    mapping_path = Path(mapping_path)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(mapping_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        existing = {}
    if not isinstance(existing, dict):
        raise ValueError("Invalid media registry")
    existing[video_id] = {"path": str(media), "verified": True}
    tmp = mapping_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(mapping_path)
