"""Exact-ID local media discovery for future offline caption generation.

This module never downloads media, invokes YouTube, or guesses associations
from titles/stream numbers. Recognition is deliberately separate.
"""
from __future__ import annotations

from pathlib import Path

MEDIA_EXTENSIONS = (".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav")
VIDEO_ID_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def valid_video_id(video_id: str) -> bool:
    return len(video_id) == 11 and all(ch in VIDEO_ID_CHARACTERS for ch in video_id)


def find_exact_local_media(video_id: str, roots: list[Path]) -> Path | None:
    """Find a locally available media file named <video_id>.<extension>.

    No recursive traversal of NAS shares. This prevents very expensive disk
    crawls and false matches on stream fragments.
    """
    if not valid_video_id(video_id):
        return None
    for root in roots:
        for extension in MEDIA_EXTENSIONS:
            candidate = Path(root) / (video_id + extension)
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
            except (OSError, ValueError):
                continue
    return None
