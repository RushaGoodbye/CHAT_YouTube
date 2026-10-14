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


def discover_title_candidates(video_title: str, roots: list[Path], *, limit: int = 5):
    """Read-only top-level candidates; never automatically binds a media file.

    Returns candidates for human confirmation. Exact ID matching remains the
    only unattended path.
    """
    from difflib import SequenceMatcher
    import re
    def normalize(value: str) -> str:
        return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))
    wanted = normalize(video_title)
    if not wanted:
        return []
    results = []
    for root in roots:
        try:
            entries = list(Path(root).iterdir())
        except OSError:
            continue
        for path in entries:
            if path.suffix.lower() not in MEDIA_EXTENSIONS or not path.is_file():
                continue
            score = SequenceMatcher(None, wanted, normalize(path.stem)).ratio()
            if score >= 0.45:
                results.append((round(score, 3), path))
    return sorted(results, key=lambda row: (-row[0], str(row[1])))[:limit]
