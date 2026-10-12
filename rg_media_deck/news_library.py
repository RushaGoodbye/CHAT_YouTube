"""Keep RG Media Deck's dedicated NEWS tab separate from main media library.

A chosen folder can sit inside an existing main library root. Files under
the news root belong exclusively to NEWS, never duplicated in MAIN.
Only photo/video formats are shown in NEWS; standalone audio stays in MAIN.
No media files are moved, copied, deleted or rewritten.
"""
from __future__ import annotations

import os
from pathlib import Path
from library import MediaItem, VIDEO_EXTS, normalize_path

AUDIO_ONLY_EXTS = frozenset({
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".opus",
})
NEWS_VIDEO_EXTS = VIDEO_EXTS - AUDIO_ONLY_EXTS


def combined_roots(main_roots: list[str], news_folder: str) -> list[str]:
    roots = [*main_roots, news_folder] if news_folder else list(main_roots)
    unique = {}
    for value in roots:
        if value and isinstance(value, str):
            unique.setdefault(normalize_path(value), value)
    # One recursive observer is enough for a parent folder. Duplicating the
    # observer for NEWS nested inside FACTAGE produced duplicate change events,
    # repeated scans, and pressure on Windows/NAS while switching video.
    roots = list(unique.items())
    result = []
    for key, original in roots:
        covered = False
        for other, _ in roots:
            if key == other:
                continue
            try:
                if os.path.commonpath((key, other)) == other:
                    covered = True
                    break
            except (OSError, ValueError):
                continue
        if not covered:
            result.append(original)
    return result


def belongs_to_news(path: str, news_folder: str) -> bool:
    if not news_folder:
        return False
    try:
        root = normalize_path(news_folder)
        child = normalize_path(path)
        return os.path.commonpath((root, child)) == root
    except (OSError, ValueError):
        return False


def news_file(item: MediaItem) -> bool:
    return (item.kind == "photo" or Path(item.path).suffix.casefold() in NEWS_VIDEO_EXTS)


def in_tab(item: MediaItem, news_folder: str, tab: str) -> bool:
    is_news = belongs_to_news(item.path, news_folder)
    if tab == "news":
        return is_news and news_file(item)
    if tab == "main":
        return not is_news
    raise ValueError("Unknown media tab")


def scoped_count(media: list[MediaItem], news_folder: str, tab: str) -> int:
    return sum(1 for item in media if in_tab(item, news_folder, tab))
