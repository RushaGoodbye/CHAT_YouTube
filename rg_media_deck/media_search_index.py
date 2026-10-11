"""Precomputed offline search index for large RG Media Deck libraries.

Build only after scan or tag edits; typing searches never re-normalize all
filenames and metadata. Keeps the same match semantics as filter_media().
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from library import MediaItem, normalize_path
from media_intelligence import fold, variants


@dataclass(frozen=True, slots=True)
class _Entry:
    item: MediaItem
    key: str
    searchable: str
    sort_name: str
    sort_path: str


class IndexedMediaLibrary:
    def __init__(self, media: Iterable[MediaItem] = (),
                 tags: dict[str, list[str]] | None = None):
        tags = tags or {}
        entries = []
        for item in media:
            key = normalize_path(item.path)
            tag_text = [fold(tag) for tag in tags.get(key, ())
                        if isinstance(tag, str)]
            entries.append(_Entry(
                item=item, key=key,
                searchable=" ".join([fold(item.name), *tag_text]),
                sort_name=item.name.casefold(),
                sort_path=item.path.casefold()))
        self._entries = tuple(entries)

    def __len__(self):
        return len(self._entries)

    def filter(self, query: str, kind: str = "all",
               favorites: set[str] | None = None,
               favorites_only: bool = False) -> list[MediaItem]:
        favorites = favorites or set()
        search_patterns = tuple(tuple(value.split()) for value in variants(query))
        matching = []
        for entry in self._entries:
            if kind != "all" and entry.item.kind != kind:
                continue
            if favorites_only and entry.key not in favorites:
                continue
            if search_patterns and not any(
                all(word in entry.searchable for word in words)
                for words in search_patterns
            ):
                continue
            matching.append(entry)
        matching.sort(key=lambda entry: (
            entry.key not in favorites, entry.sort_name, entry.sort_path))
        return [entry.item for entry in matching]
