"""Persist only captions fetched for the requested YouTube video ID.

The acquisition record represents request provenance, not proof of semantic
accuracy. The editorial system must still review content and factual claims.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .seo_caption_manifest import audit_caption_file, make_source_manifest


def rows_to_srt(rows: Iterable[dict[str, Any]]) -> bytes:
    """Lossless-enough text/timing serialization, with strict row validation."""
    output: list[str] = []
    for i, item in enumerate(rows, 1):
        start = float(item.get("start", -1))
        duration = float(item.get("duration", -1))
        caption = " ".join(str(item.get("text") or "").split())
        if not caption or start < 0 or duration <= 0 or not (
            start < 172800 and duration < 172800
        ):
            raise ValueError("INVALID_CAPTION_ROW")
        output.append(
            f"{i}\n{_stamp(start)} --> {_stamp(start + duration)}\n{caption}"
        )
    if not output:
        raise ValueError("EMPTY_CAPTIONS")
    return ("\n\n".join(output) + "\n").encode("utf-8")


def _stamp(value: float) -> str:
    milliseconds = round(value * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def acquire_caption_rows(
    *, video_id: str, rows: list[dict[str, Any]], duration_s: float,
    cache_dir: Path, acquisition_method: str = "youtube_direct",
) -> dict[str, Any]:
    """Validate then atomically cache a directly retrieved caption response.

    Caller MUST obtain rows through a request for this exact video ID; never
    pass rows from an unrelated local file or generate a fake source record.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return {"status": "BLOCKED_SOURCE", "issues": ["INVALID_VIDEO_ID"]}
    try:
        raw = rows_to_srt(rows)
        manifest = make_source_manifest(
            video_id=video_id, srt_bytes=raw,
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            acquisition_method=acquisition_method,
            acquired_at=datetime.now(timezone.utc).isoformat(),
            duration_s=duration_s,
            verification="youtube_caption_response",
        )
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{video_id}.srt"
        record = target.with_suffix(".source.json")
        # A failure in staging must not destroy an older verified cache.
        staging = cache_dir / f"{video_id}.stage.srt"
        staging_record = staging.with_suffix(".source.json")
        try:
            staging.write_bytes(raw)
            staging_record.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            audit = audit_caption_file(
                video_id=video_id, path=staging, duration_s=duration_s,
            )
            if audit["status"] == "BLOCKED_SOURCE":
                return audit
            # Both files are stored locally, never on the NAS by this method.
            staging.replace(target)
            staging_record.replace(record)
            return audit
        finally:
            staging.unlink(missing_ok=True)
            staging_record.unlink(missing_ok=True)
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        return {"status": "BLOCKED_SOURCE", "issues": [type(exc).__name__ + ": " + str(exc)]}
