"""Read-only zero-YouTube-Data-API source recovery probe for public 3h+ LIVE archives.

Runs only on ALEXPC. Uses existing public yt-dlp and caption clients, without
saving transcripts, video IDs, titles, descriptions, URLs, or tags anywhere.
Only coarse anonymous counters are written into GitHub Actions artifact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Callable

from rg_youtube_control.config import app_data_dir
from rg_youtube_control.cached_metadata import cached_public_metadata, yt_dlp_auth_blocked
from rg_youtube_control.dialogue_seo import split_timeline
from rg_youtube_control.free_tools import (
    fetch_public_metadata, fetch_transcript,
    fetch_transcript_from_public_metadata,
)
from rg_youtube_real_live_seo_qa import MIN_LONG_LIVE_SECONDS, _captions_span_full_long_live

OUTPUT = Path("rg_youtube_long_live_public_source_anonymous.json")


def run(
    *, max_videos: int = 5,
    db_path: Path | None = None,
    metadata_fetch: Callable = fetch_public_metadata,
    transcript_fetch: Callable = fetch_transcript,
    track_fetch: Callable = fetch_transcript_from_public_metadata,
) -> dict:
    result = {
        "schema": "RG_LONG_LIVE_PUBLIC_SOURCE_PREFLIGHT_V1",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "NOT_READY",
        "mode": "PUBLIC_YT_DLP_AND_CAPTIONS_READ_ONLY",
        "youtube_data_api_calls": 0,
        "youtube_modified": False,
        "nas_modified": False,
        "ollama_called": False,
        "source_text_exported": False,
        "source_identifiers_exported": False,
        "generated_content_exported": False,
        "private_metadata_saved": False,
        "public_long_candidates": 0,
        "probed_count": 0,
        "public_metadata_retrieved": 0,
        "public_metadata_access_denied": 0,
        "metadata_identifier_mismatches": 0,
        "original_description_retrieved": 0,
        "original_tags_retrieved": 0,
        "duration_mismatch_count": 0,
        "captions_retrieved": 0,
        "full_span_caption_sources": 0,
        "ready_source_candidates": 0,
    }
    try:
        cap = max(0, min(int(max_videos), 5))
    except (TypeError, ValueError, OverflowError):
        result["reason"] = "Invalid public source probe limit"
        return result
    db = db_path or app_data_dir() / "rg_youtube_control.db"
    if not db.is_file():
        result["reason"] = "Synchronized local metadata unavailable"
        return result
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            """SELECT video_id FROM videos
               WHERE profile='live' AND scheduled_publish_at IS NULL
                 AND COALESCE(privacy_status,'public')='public'"""
        ).fetchall()
        eligible = []
        for (video_id,) in rows:
            if not isinstance(video_id, str) or len(video_id) != 11:
                continue
            cached = cached_public_metadata(conn, video_id, "live")
            duration = int(cached.get("duration") or 0)
            if duration >= MIN_LONG_LIVE_SECONDS:
                eligible.append((video_id, duration))
        conn.close()
    except sqlite3.Error:
        result["reason"] = "Local database could not be read"
        return result

    result["public_long_candidates"] = len(eligible)
    # Longer verified archives first, then deterministic video ID ordering.
    eligible.sort(key=lambda row: (-row[1], row[0]))
    for video_id, cached_duration in eligible[:cap]:
        result["probed_count"] += 1
        metadata = {}
        try:
            metadata = dict(metadata_fetch(video_id) or {})
        except Exception as exc:
            if yt_dlp_auth_blocked(exc):
                result["public_metadata_access_denied"] += 1
            # Metadata can be bot-blocked while the independent transcript API
            # remains available. Probe captions anyway but never claim a
            # complete SEO source without the original description.
        if metadata and str(metadata.get("video_id") or "") != video_id:
            result["metadata_identifier_mismatches"] += 1
            continue
        description_found = False
        duration_seconds = cached_duration
        if metadata:
            result["public_metadata_retrieved"] += 1
            description_found = bool(str(metadata.get("description") or "").strip())
            if description_found:
                result["original_description_retrieved"] += 1
            if metadata.get("tags"):
                result["original_tags_retrieved"] += 1
            try:
                remote_duration = int(metadata.get("duration") or 0)
            except (ValueError, TypeError, OverflowError):
                remote_duration = 0
            if remote_duration and remote_duration < MIN_LONG_LIVE_SECONDS:
                result["duration_mismatch_count"] += 1
                continue
            duration_seconds = remote_duration or cached_duration
        captions = []
        try:
            captions = list(transcript_fetch(video_id) or [])
        except Exception:
            captions = []
        if not captions and metadata:
            try:
                captions = list(track_fetch(metadata, timeout=15.0) or [])
            except Exception:
                captions = []
        if not captions:
            continue
        result["captions_retrieved"] += 1
        if not _captions_span_full_long_live(captions, duration_seconds):
            continue
        try:
            timeline_blocks = len(split_timeline(
                captions, max_chars=5000, max_span_seconds=300
            ))
        except (ValueError, TypeError, OverflowError):
            continue
        if timeline_blocks < 15:
            continue
        result["full_span_caption_sources"] += 1
        if description_found:
            result["ready_source_candidates"] += 1

    if result["ready_source_candidates"]:
        result["status"] = "SOURCE_READY"
        result["reason"] = "At least one 3h+ public LIVE has original metadata and full-span captions"
    elif not eligible:
        result["reason"] = "No verified long LIVE metadata in synchronized local database"
    else:
        result["reason"] = "No complete public LIVE source in bounded zero-Data-API probe"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Zero-Data-API public LIVE preflight")
    parser.add_argument("--max-videos", type=int, default=5)
    args = parser.parse_args()
    result = run(max_videos=args.max_videos)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    for key in (
        "status", "public_long_candidates", "probed_count",
        "public_metadata_retrieved", "public_metadata_access_denied",
        "original_description_retrieved", "original_tags_retrieved",
        "captions_retrieved", "full_span_caption_sources", "ready_source_candidates",
        "duration_mismatch_count", "reason",
    ):
        print("PUBLIC LONG LIVE " + key.upper() + ":", result.get(key), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
