"""Non-destructive thematic collections for RG Media Deck.

Collections reference original absolute paths. They never move or copy videos.
"""
from __future__ import annotations
import os


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(path))))

def clean_collections(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, list[str]] = {}
    for raw_name, raw_paths in list(value.items())[:100]:
        if not isinstance(raw_name, str) or not isinstance(raw_paths, (list, tuple)):
            continue
        name = raw_name.strip()[:60]
        if not name or any(x in name for x in "\r\n\t"):
            continue
        paths = []
        seen = set()
        for raw in raw_paths[:5000]:
            if not isinstance(raw, str) or not raw.strip():
                continue
            key = normalize_path(raw)
            if key not in seen:
                seen.add(key)
                paths.append(key)
        clean[name] = paths
    return clean

def add_files(collections: dict[str, list[str]], name: str,
              files: list[str]) -> dict[str, list[str]]:
    name = name.strip()
    if not name or len(name) > 60 or any(c in name for c in "\r\n\t"):
        raise ValueError("Некоректна назва добірки")
    result = {key: list(values) for key, values in collections.items()}
    existing = result.setdefault(name, [])
    seen = set(existing)
    for file in files:
        key = normalize_path(file)
        if key not in seen:
            existing.append(key)
            seen.add(key)
    return result

def remove_file_references(collections: dict[str, list[str]],
                           paths: list[str]) -> dict[str, list[str]]:
    removed = {normalize_path(x) for x in paths}
    return {name: [p for p in members if p not in removed]
            for name, members in collections.items()}

def migrate_path(collections: dict[str, list[str]], previous: str,
                 updated: str) -> dict[str, list[str]]:
    old, new = normalize_path(previous), normalize_path(updated)
    result = {}
    for name, members in collections.items():
        out = []
        for member in members:
            value = new if member == old else member
            if value not in out:
                out.append(value)
        result[name] = out
    return result
