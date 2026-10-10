"""Owner-authorized read-only source check for five LIVE videos.

Uses a single YouTube Data API videos.list call only if a LIVE profile is
already connected. No OAuth browser, no authentication prompts, and no
metadata/NAS writes. Only anonymous counts may leave ALEXPC.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Callable

from rg_youtube_control.cached_metadata import cached_public_metadata
from rg_youtube_control.config import app_data_dir
from rg_youtube_control.youtube_api import YouTubeClient
from rg_youtube_real_live_seo_qa import MIN_LONG_LIVE_SECONDS

OUTPUT = Path("rg_youtube_long_live_owner_source_anonymous.json")


def run(
    *, db_path: Path | None = None,
    max_videos: int = 5,
    client_factory: Callable = YouTubeClient,
) -> dict:
    result = {
        "schema": "RG_LONG_LIVE_OWNER_SOURCE_PROBE_V1",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "NOT_READY",
        "mode": "OWNER_AUTH_READ_ONLY_VIDEOS_LIST",
        "source_text_exported": False,
        "source_identifiers_exported": False,
        "credentials_exported": False,
        "youtube_modified": False,
        "nas_modified": False,
        "db_modified": False,
        "ollama_called": False,
        "oauth_browser_opened": False,
        "long_candidates": 0,
        "requested_ids": 0,
        "youtube_data_api_calls": 0,
        "videos_returned": 0,
        "source_descriptions_available": 0,
        "source_tags_available": 0,
        "channel_id_mismatch": 0,
        "owner_profile_authorized": False,
    }
    cap = max(0, min(int(max_videos), 5))
    db = db_path or (app_data_dir() / "rg_youtube_control.db")
    if not db.is_file():
        result["reason"] = "Local synchronized LIVE database unavailable"
        return result
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        entries = conn.execute(
            """SELECT video_id, COALESCE(channel_id,'') FROM videos
               WHERE profile='live' AND scheduled_publish_at IS NULL
                 AND COALESCE(privacy_status,'public')='public'"""
        ).fetchall()
        selected = []
        for video_id, channel_id in entries:
            if not isinstance(video_id, str) or len(video_id) != 11:
                continue
            cached = cached_public_metadata(conn, video_id, "live")
            if int(cached.get("duration") or 0) < MIN_LONG_LIVE_SECONDS:
                continue
            selected.append((video_id, channel_id))
        conn.close()
    except sqlite3.Error:
        result["reason"] = "Read-only LIVE database query failed"
        return result
    result["long_candidates"] = len(selected)
    selected.sort()
    selected = selected[:cap]
    if not selected:
        result["reason"] = "No long LIVE candidates with verified cached duration"
        return result
    video_ids = [video_id for video_id, _ in selected]
    channels = {video_id: channel for video_id, channel in selected}
    result["requested_ids"] = len(video_ids)
    try:
        client = client_factory(profile="live")
        # A pre-existing owner token is mandatory. No authorize() call.
        client.credentials()
        result["owner_profile_authorized"] = True
        items, count = client.video_details_with_request_count(video_ids)
    except Exception:
        result["reason"] = "Existing LIVE profile owner authorization or read-only API unavailable"
        return result
    result["youtube_data_api_calls"] = int(count)
    # videos.list is the low-cost 1-unit read endpoint, 50 IDs max.
    returned = set()
    for item in items or []:
        vid = str(item.get("id") or "")
        if vid not in channels or vid in returned:
            continue
        returned.add(vid)
        snippet = dict(item.get("snippet") or {})
        stored_channel = str(channels[vid] or "")
        remote_channel = str(snippet.get("channelId") or "")
        if stored_channel and remote_channel != stored_channel:
            result["channel_id_mismatch"] += 1
            continue
        result["videos_returned"] += 1
        if str(snippet.get("description") or "").strip():
            result["source_descriptions_available"] += 1
        if snippet.get("tags"):
            result["source_tags_available"] += 1
    result["status"] = "SOURCE_READY" if result["source_descriptions_available"] else "NOT_READY"
    result["reason"] = (
        "Owner video descriptions available for secure local recovery"
        if result["source_descriptions_available"]
        else "Owner metadata returned no usable original long LIVE descriptions"
    )
    return result


def main() -> int:
    result = run()
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    for key in (
        "status", "long_candidates", "requested_ids", "owner_profile_authorized",
        "youtube_data_api_calls", "videos_returned",
        "source_descriptions_available", "source_tags_available",
        "channel_id_mismatch", "reason",
    ):
        print("OWNER LIVE " + key.upper() + ":", result.get(key), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
