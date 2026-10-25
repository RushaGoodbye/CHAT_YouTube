"""Read-only historical title candidates for manual evidence review.

Never upgrades a suggested title match into a verified media binding.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .local_media_sources import discover_title_candidates


def historical_media_candidates(
    conn: sqlite3.Connection, video_id: str, roots: list[Path], limit: int = 8
) -> list[tuple[float, Path, str]]:
    titles = []
    row = conn.execute("SELECT title FROM videos WHERE video_id=?", (video_id,)).fetchone()
    if row and row[0]:
        titles.append(str(row[0]))
    for (title,) in conn.execute(
        "SELECT DISTINCT title FROM metadata_history WHERE video_id=? ORDER BY created_at ASC",
        (video_id,),
    ):
        if title and title not in titles:
            titles.append(str(title))
    candidates = {}
    for title in titles:
        for score, path in discover_title_candidates(title, roots, limit=limit):
            key = str(path)
            if key not in candidates or score > candidates[key][0]:
                candidates[key] = (score, path, title)
    return sorted(candidates.values(), key=lambda x: (-x[0], str(x[1])))[:limit]
