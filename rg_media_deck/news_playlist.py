"""Deterministic NEWS playlist progression.

The current, filtered and sorted list is snapshotted when playback begins.
No wrap-around: after the last item the broadcast player stops.
"""
from __future__ import annotations

from typing import Callable
from library import MediaItem


def next_news_item(items: list[MediaItem], current_path: str,
                   exists: Callable[[str], bool]) -> MediaItem | None:
    """Return next available item after current, never replay or wrap."""
    index = next((i for i, item in enumerate(items) if item.path == current_path), -1)
    if index < 0:
        return None
    for item in items[index + 1:]:
        if exists(item.path):
            return item
    return None
