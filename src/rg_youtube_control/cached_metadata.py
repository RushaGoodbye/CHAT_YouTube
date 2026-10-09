"""Authenticated-own-channel metadata cache as a safe read-only SEO fallback.

No browser cookies, external authentication, YouTube Data API calls, or writes.
The videos table is the authoritative cached title/status; metadata_history
and optimization_drafts.source_* can supply the original description and tags.
A generated draft description must NEVER be mistaken for source metadata.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any


def _cached_duration_seconds(value: object) -> int:
    raw = str(value or "").strip()
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    if 2 <= len(parts) <= 3 and all(item.isdigit() for item in parts):
        seconds = 0
        for item in parts:
            seconds = 60 * seconds + int(item)
        return seconds
    match = re.fullmatch(
        r"P(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)", raw, re.I
    )
    if match:
        hours, minutes, seconds = (int(v or 0) for v in match.groups())
        return hours * 3600 + minutes * 60 + seconds
    return 0


def _tags_from_json(value: object) -> list[str]:
    try:
        raw = json.loads(str(value or "[]"))
    except (ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    return [
        item.strip() for item in raw
        if isinstance(item, str) and item.strip()
    ]


def cached_public_metadata(
    conn: sqlite3.Connection,
    video_id: str,
    profile: str,
) -> dict[str, Any]:
    """Get cached *original* video metadata without any network requests.

    Returns a distinct source marker for the preview, so offline fields are
    never represented as if yt-dlp fetched them just now.
    """
    video = conn.execute(
        """SELECT title, duration, views, channel_id, privacy_status,
                  scheduled_publish_at, published_at
           FROM videos WHERE video_id=? AND profile=?""",
        (video_id, profile),
    ).fetchone()
    if not video or not str(video[0] or "").strip():
        return {}

    original = conn.execute(
        """SELECT source_description, source_tags_json
           FROM optimization_drafts WHERE video_id=?""",
        (video_id,),
    ).fetchone()
    history = conn.execute(
        """SELECT description, tags_json
           FROM metadata_history WHERE video_id=?
           ORDER BY created_at DESC, history_id DESC LIMIT 1""",
        (video_id,),
    ).fetchone()
    description = (
        str(original[0] or "").strip()
        if original and str(original[0] or "").strip()
        else str(history[0] or "").strip() if history else ""
    )
    tags = _tags_from_json(original[1]) if original else []
    if not tags and history:
        tags = _tags_from_json(history[1])
    return {
        "video_id": video_id,
        "title": str(video[0]).strip(),
        "description": description,
        "tags": tags,
        "duration": _cached_duration_seconds(video[1]),
        "view_count": int(video[2] or 0),
        "channel_id": str(video[3] or ""),
        "privacy_status": str(video[4] or ""),
        "scheduled_publish_at": str(video[5] or ""),
        "upload_date": str(video[6] or "")[:10].replace("-", ""),
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "_caption_tracks": {},
        "source": "sqlite-cache",
        "source_description_available": bool(description),
        "youtube_data_api_quota": 0,
    }


def yt_dlp_auth_blocked(exc: BaseException | str) -> bool:
    """Recognize a YouTube bot/auth challenge as a recoverable read failure."""
    message = str(exc).casefold()
    return any(
        token in message for token in (
            "sign in to confirm you're not a bot",
            "sign in to confirm you’re not a bot",
            "cookies-from-browser",
            "use --cookies",
            "confirm you are not a bot",
            "confirm you're not a bot",
            "http error 403",
            "http error 429",
        )
    )
