"""Read-only public YouTube comment sample for editorial research.

Uses the MIT-licensed egbertbouman/youtube-comment-downloader library.
Never touches YouTube authentication, moderation queues, the local comment DB,
likes, replies or any YouTube Data API quota.
"""
from __future__ import annotations

import re
import time
from typing import Any


def csv_safe_public_comment_cell(value: object) -> str:
    """Escape untrusted public text so Excel cannot execute CSV formulas."""
    raw = str(value or "")
    if raw.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + raw
    return raw


def fetch_public_comment_sample(
    video_id: str,
    *,
    limit: int = 100,
    time_budget_seconds: float = 30.0,
) -> dict[str, Any]:
    clean_id = str(video_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", clean_id) is None:
        raise ValueError("Некоректний ідентифікатор YouTube відео.")
    if not 1 <= int(limit) <= 200:
        raise ValueError("Ліміт має бути від 1 до 200 коментарів.")

    from youtube_comment_downloader import (  # MIT, external public data only
        SORT_BY_RECENT,
        YoutubeCommentDownloader,
    )

    url = f"https://www.youtube.com/watch?v={clean_id}"
    downloader = YoutubeCommentDownloader()
    rows: list[dict[str, str]] = []
    started = time.monotonic()
    # This is a best-effort budget between comments; a request already in
    # progress is controlled by the upstream library.
    for item in downloader.get_comments_from_url(url, sort_by=SORT_BY_RECENT):
        if time.monotonic() - started > time_budget_seconds:
            break
        if not isinstance(item, dict):
            continue
        comment_id = str(item.get("cid") or item.get("id") or "").strip()
        message = str(item.get("text") or "").strip()
        if not message:
            continue
        rows.append({
            "video_id": clean_id,
            "comment_id": comment_id,
            "author": str(item.get("author") or ""),
            "comment": message,
            "published": str(item.get("time") or ""),
            "votes": str(item.get("votes") or ""),
            "source": "public-youtube-page",
        })
        if len(rows) >= int(limit):
            break
    return {
        "video_id": clean_id,
        "comments": rows,
        "youtube_data_api_units": 0,
        "read_only": True,
    }
