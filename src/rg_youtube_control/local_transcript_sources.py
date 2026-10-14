"""Offline, exact-Video-ID transcript discovery for SEO.

Do not search by title or stream number: that cannot establish provenance.
No network or YouTube writes are performed here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .free_tools import load_srt_transcript, parse_webvtt_transcript


def find_local_transcript(directory: Path, video_id: str) -> tuple[list[dict[str, Any]], str]:
    """Return caption rows and evidence source, or ([], '').

    Restrict to exact video IDs to avoid silently attaching unrelated dialogue
    transcripts. Handles cached SRT and WebVTT.
    """
    if len(video_id) != 11 or not all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in video_id):
        return [], ""
    root = Path(directory)
    # yt-dlp and caption exporters commonly append language codes.
    # Only explicit, exact-ID filenames are eligible (never fuzzy matches).
    suffixes = (
        "", ".uk", ".ru", ".en", ".uk-orig", ".ru-orig", ".en-orig",
    )
    for extension, suffix in (
        (ext, lang) for lang in suffixes for ext in (".srt", ".vtt")
    ):
        path = root / (video_id + suffix + extension)
        try:
            if not path.is_file():
                continue
            if extension == ".srt":
                rows = load_srt_transcript(path)
            else:
                rows = parse_webvtt_transcript(path.read_text(encoding="utf-8-sig", errors="replace"))
            if rows and any(str(row.get("text") or "").strip() for row in rows):
                return rows, "nas-" + extension.removeprefix(".")
        except (OSError, ValueError, UnicodeError):
            continue
    return [], ""
