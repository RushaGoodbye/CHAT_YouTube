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


def merge_verified_public_source_metadata(
    cached: dict[str, Any],
    video_id: str,
    public: dict[str, Any],
) -> dict[str, Any]:
    """Recover missing original description without overwriting trusted title.

    Caller fetches only public metadata with yt-dlp, never YouTube Data API.
    A remote ID mismatch cannot silently contaminate another video's draft.
    This is a temporary source-only context, not a database write.
    """
    video_id = str(video_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid source video identifier")
    if str(public.get("video_id") or "") != video_id:
        raise ValueError("Public metadata refers to another video")
    if "description" not in public:
        raise ValueError("Public metadata does not include original description")
    context = dict(cached)
    if not str(context.get("title") or "").strip():
        context["title"] = str(public.get("title") or "").strip()
    if not str(context.get("title") or "").strip():
        raise ValueError("No original video title")
    if not bool(cached.get("source_description_available")):
        # Missing or empty public descriptions cannot demonstrate retention
        # of existing links. Do not silently label them verified.
        source_description = str(public.get("description") or "").strip()
        if not source_description:
            raise ValueError("Public metadata original description is empty")
        context["description"] = source_description
        context["source_description_available"] = True
        context["source_description_verified"] = True
    if not context.get("tags"):
        context["tags"] = [
            str(tag).strip() for tag in (public.get("tags") or [])
            if str(tag).strip()
        ]
    if not context.get("_caption_tracks") and public.get("_caption_tracks"):
        context["_caption_tracks"] = public["_caption_tracks"]
    context["source"] = "sqlite-plus-public-source" if cached else "yt-dlp"
    context["youtube_data_api_quota"] = 0
    return context


def recover_original_from_owner_api(
    cached: dict[str, Any],
    video_id: str,
    *,
    profile: str,
    client_factory=None,
) -> tuple[dict[str, Any], int]:
    """Last-resort ONE-REQUEST owner-only source recovery after public failure.

    No update, comment, caption-download or video mutation endpoints are used.
    Callers must check quota budget BEFORE this call and record returned reads.
    No authenticated metadata is written here; the accepted draft later
    persists its source metadata in the normal audited draft workflow.
    """
    from .config import PROFILE_TARGETS
    from .youtube_api import YouTubeClient

    expected_channel = str(cached.get("channel_id") or PROFILE_TARGETS.get(profile) or "")
    if not expected_channel:
        raise ValueError("Cannot verify LIVE channel ownership")
    factory = client_factory or YouTubeClient
    client = factory(profile=profile)
    client.credentials()  # Existing authorization only; NEVER open login UI.
    items, request_count = client.video_details_with_request_count([video_id])
    count = int(request_count)
    if count != 1:
        raise ValueError("Owner metadata lookup exceeded one request")
    for item in items or []:
        if str(item.get("id") or "") != video_id:
            continue
        snippet = dict(item.get("snippet") or {})
        if str(snippet.get("channelId") or "") != expected_channel:
            raise ValueError("Owner metadata channel does not match cached channel")
        context = merge_verified_public_source_metadata(
            cached, video_id, {
                "video_id": video_id,
                "title": snippet.get("title") or "",
                "description": snippet.get("description"),
                "tags": snippet.get("tags") or [],
            },
        )
        context["source"] = "sqlite-plus-owner-readonly"
        context["youtube_data_api_quota"] = count
        return context, count
    raise ValueError("Requested video not returned by owner read-only metadata")
