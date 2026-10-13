"""Local on-air tools: bounded history, quick slots, typo suggestions. No network."""
from __future__ import annotations
from difflib import get_close_matches
from pathlib import Path

def remember(history, path, limit=30):
    clean = [p for p in history if p != path]
    return [path] + clean[:limit - 1]

def suggest(query, items, limit=5):
    needle = query.strip().casefold()
    if len(needle) < 3:
        return []
    names = {Path(item.path).stem.casefold(): Path(item.path).stem for item in items}
    return [names[k] for k in get_close_matches(needle, names, n=limit, cutoff=0.62)]

def available(history, paths):
    return [path for path in history if path in paths]
