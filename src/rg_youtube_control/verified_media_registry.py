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
