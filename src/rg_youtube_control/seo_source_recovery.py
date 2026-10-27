"""Recover stale NAS SRT by exact-video public subtitles without weakening source gates.

No YouTube writes, no changes to saved SRT files or SQLite. The return value
can be used only for an in-memory review-only SEO draft.
"""
from __future__ import annotations

from typing import Callable

from .seo_engine_v1 import _check_source_video


def _source_text(rows: list[dict]) -> str:
    return " ".join(
        str(row.get("text") or "") for row in rows
        if isinstance(row, dict)
    )


def validate_or_recover_exact_id_rows(
    *, video_id: str, current_title: str, rows: list[dict],
    source_name: str, fetch_exact_id: Callable[[str], list[dict]],
) -> tuple[list[dict], str, bool]:
    """Return (verified rows, source name, was recovered) or fail closed.

    First validate a local SRT against the synchronized headline. If that
    evidence is missing, try only the same video's public captions, never
    adjacent files or a title-only generated summary.
    """
    original_text = _source_text(rows)
    try:
        if len(rows) < 10 or len(original_text) < 150:
            raise ValueError("SOURCE_VIDEO_MISMATCH: missing sufficient caption evidence")
        _check_source_video(current_title, original_text)
        return rows, source_name, False
    except ValueError:
        pass

    # The user's original NAS/manual content is immutable.
    # Explicitly restrict fallbacks to the exact ID supplied by the caller.
    try:
        fresh_rows = fetch_exact_id(video_id)
    except Exception:
        fresh_rows = []
    fresh_text = _source_text(fresh_rows)
    if len(fresh_rows) >= 10 and len(fresh_text) >= 150:
        try:
            _check_source_video(current_title, fresh_text)
            return fresh_rows, "youtube-exact-id-recovered", True
        except ValueError:
            pass

    raise ValueError(
        "SEO_SOURCE_IDENTITY_NOT_PROVEN: транскрипт не підтверджує тему "
        "назви; перевірено локальні субтитри та субтитри точного Video ID "
        f"{video_id}. Чернетку не створено. YouTube і SRT не змінено."
    )
