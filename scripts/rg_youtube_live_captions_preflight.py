"""Read-only discovery of alternative caption sources for the LIVE channel.

Keeps video IDs, captions, titles and URLs on ALEXPC. Output is anonymous
availability counters ONLY. No YouTube Data API requests, no writes to NAS.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Callable

from rg_youtube_control.config import (
    DEFAULT_NAS_TRANSCRIPTS_PATH, app_data_dir, normalize_nas_unc_path,
)
from rg_youtube_control.free_tools import (
    fetch_public_metadata, fetch_transcript, fetch_transcript_from_public_metadata,
    load_srt_transcript,
)
from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks

OUTPUT = Path("rg_youtube_live_captions_anonymous_preflight.json")


def inspect(
    *,
    db_path: Path | None = None,
    transcript_dir: Path | None = None,
    public_transcript: Callable[[str], list] = fetch_transcript,
    metadata: Callable[[str], dict] = fetch_public_metadata,
    metadata_captions: Callable[[dict], list] = fetch_transcript_from_public_metadata,
    max_public_probes: int = 2,
) -> dict:
    """Try at most two public caption lookups, no login/cookies or uploads."""
    outcome = {
        "schema": "RG_LIVE_CAPTION_SOURCES_V1",
        "mode": "READ_ONLY_PUBLIC_CAPTIONS_NO_YOUTUBE_DATA_API",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "NOT_READY",
        "known_live_archive_rows": 0,
        "public_archive_rows": 0,
        "nas_srt_matched": 0,
        "public_checked": 0,
        "public_transcript_available": 0,
        "yt_dlp_captions_available": 0,
        "no_caption_source_found": 0,
        "live_timeline_integrity_checked": 0,
        "live_timeline_integrity_passed": 0,
        "live_caption_rows_analyzed": 0,
        "source_text_exported": False,
        "video_ids_exported": False,
        "youtube_data_api_calls": 0,
        "youtube_modified": False,
        "nas_modified": False,
    }
    db = db_path or app_data_dir() / "rg_youtube_control.db"
    if not db.is_file():
        outcome["reason"] = "Local synchronized database is unavailable"
        return outcome
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            """SELECT video_id, COALESCE(privacy_status,'public'),
                      scheduled_publish_at FROM videos WHERE profile='live'"""
        ).fetchall()
        setting = conn.execute(
            "SELECT value FROM settings WHERE key='nas_transcripts_path'"
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        outcome["reason"] = "Read-only local database query failed"
        return outcome

    outcome["known_live_archive_rows"] = sum(
        not str(scheduled or "").strip() for _, _, scheduled in rows
    )
    eligible = [
        identifier for identifier, privacy, scheduled in rows
        if isinstance(identifier, str) and len(identifier) == 11
        and not str(scheduled or "").strip()
        and str(privacy).casefold() == "public"
    ]
    outcome["public_archive_rows"] = len(eligible)
    if not eligible:
        outcome["status"] = "NO_PUBLIC_ARCHIVES"
        outcome["reason"] = "No public archived LIVE video records in local database"
        return outcome

    raw = str(setting[0] or "").strip() if setting else ""
    directory = transcript_dir or Path(
        normalize_nas_unc_path(raw, DEFAULT_NAS_TRANSCRIPTS_PATH)
    )
    missing = []
    for identifier in eligible:
        path = directory / f"{identifier}.srt"
        try:
            if path.is_file() and 0 < path.stat().st_size < 30_000_000:
                if load_srt_transcript(path):
                    outcome["nas_srt_matched"] += 1
                    continue
        except (OSError, ValueError):
            pass
        missing.append(identifier)
    if outcome["nas_srt_matched"] > 0:
        outcome["status"] = "NAS_AVAILABLE"
        outcome["reason"] = "At least one LIVE SRT is accessible on NAS"
        return outcome

    def count_full_caption_coverage(captions: list) -> None:
        # This analyzes every caption with a deterministic empty-topic stub.
        # It NEVER calls Ollama or exports transcript text; semantic quality
        # is deliberately not claimed in this infrastructure preflight.
        try:
            report = analyze_all_timeline_blocks(
                captions, model="live-coverage-readonly",
                chat=lambda *_args, **_kwargs: '{"topics":[]}',
                max_chars=5000, max_span_seconds=300,
            )
        except (ValueError, TypeError, RuntimeError, OSError):
            return
        outcome["live_timeline_integrity_checked"] += 1
        outcome["live_caption_rows_analyzed"] += int(
            report.get("source_rows_with_text") or 0
        )
        if (
            report.get("source_integrity_verified") is True
            and report.get("blocks_total") == report.get("blocks_analyzed")
        ):
            outcome["live_timeline_integrity_passed"] += 1

    for identifier in missing[:max(0, min(max_public_probes, 2))]:
        outcome["public_checked"] += 1
        try:
            captions = public_transcript(identifier)
            if captions:
                outcome["public_transcript_available"] += 1
                count_full_caption_coverage(captions)
                continue
        except Exception:
            pass
        try:
            context = metadata(identifier)
            captions = metadata_captions(context) if context else []
            if captions:
                outcome["yt_dlp_captions_available"] += 1
                count_full_caption_coverage(captions)
                continue
        except Exception:
            pass
        outcome["no_caption_source_found"] += 1
    if outcome["public_transcript_available"] or outcome["yt_dlp_captions_available"]:
        outcome["status"] = "PUBLIC_CAPTIONS_AVAILABLE"
        outcome["reason"] = "Public captions available without NAS SRT"
    elif outcome["public_checked"]:
        outcome["status"] = "NO_CAPTIONS_IN_SAMPLE"
        outcome["reason"] = "Sampled LIVE video captions not publicly available"
    else:
        outcome["status"] = "NOT_PROBED"
        outcome["reason"] = "No public caption lookup performed"
    return outcome


def main() -> int:
    try:
        result = inspect()
    except Exception:
        result = {
            "schema": "RG_LIVE_CAPTION_SOURCES_V1",
            "status": "NOT_READY",
            "reason": "Unexpected local diagnostic error",
            "source_text_exported": False,
            "video_ids_exported": False,
        }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("LIVE CAPTIONS:", result["status"], flush=True)
    for key in ("known_live_archive_rows", "public_archive_rows", "nas_srt_matched",
                "public_checked", "public_transcript_available",
                "yt_dlp_captions_available", "no_caption_source_found",
                "live_timeline_integrity_checked", "live_timeline_integrity_passed",
                "live_caption_rows_analyzed"):
        print(key.upper() + ":", result.get(key, 0), flush=True)
    print("REASON:", result.get("reason", ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
