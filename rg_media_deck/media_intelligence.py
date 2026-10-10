"""Fast, deterministic search over media names and user tags.

Supports swapped RU/EN keyboard layouts and Ukrainian letters in the wrong
layout. No network requests or AI model needed during live broadcasts.
"""
from __future__ import annotations

import re
import unicodedata

LATIN = "qwertyuiop[]asdfghjkl;'zxcvbnm,."
CYRILLIC = "йцукенгшщзхъфывапролджэячсмитьбю"
LATIN_TO_RU = str.maketrans(LATIN + LATIN.upper(), CYRILLIC + CYRILLIC.upper())
RU_TO_LATIN = str.maketrans(CYRILLIC + CYRILLIC.upper(), LATIN + LATIN.upper())
# Keyboard's Ukrainian ї/є/і/ґ are mapped from physical keys whenever needed.
UK_EXTRA = {"s": "і", "'": "є", "]": "ї", "`": "ґ"}
UK_TRANSLATIONS = str.maketrans(UK_EXTRA)

def fold(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value)).casefold().replace("ё", "е")
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))

def variants(query: str) -> tuple[str, ...]:
    folded = fold(query)
    options = [folded, fold(query.translate(LATIN_TO_RU)),
               fold(query.translate(RU_TO_LATIN))]
    if any("a" <= ch.lower() <= "z" for ch in query):
        options.append(fold(query.translate(UK_TRANSLATIONS)))
    return tuple(dict.fromkeys(x for x in options if x))

def search_match(query: str, name: str, tags=()) -> bool:
    terms = [fold(name)] + [fold(tag) for tag in tags if isinstance(tag, str)]
    haystack = " ".join(terms)
    if not query.strip():
        return True
    return any(all(part in haystack for part in alternate.split())
               for alternate in variants(query))

def clean_tags(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    seen, result = set(), []
    for raw in value[:30]:
        if not isinstance(raw, str):
            continue
        tag = raw.strip()[:48]
        if tag and fold(tag) not in seen:
            result.append(tag)
            seen.add(fold(tag))
    return result

def add_bookmark(bookmarks: dict, file_key: str, milliseconds: int, note: str) -> dict:
    if not file_key or not isinstance(milliseconds, int) or milliseconds < 0:
        raise ValueError("Некоректний час мітки")
    result = {key: [dict(point) for point in markers] for key, markers in bookmarks.items()}
    markers = result.setdefault(file_key, [])
    point = {"ms": milliseconds, "note": note.strip()[:100] if isinstance(note, str) else ""}
    # Replace a near-identical marker rather than creating accidental duplicates.
    markers = [m for m in markers if abs(m["ms"] - milliseconds) > 1000]
    markers.append(point)
    result[file_key] = sorted(markers, key=lambda m: m["ms"])[:100]
    return result

def clean_bookmarks(value) -> dict[str, list[dict]]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, points in list(value.items())[:5000]:
        if not isinstance(key, str) or not isinstance(points, list):
            continue
        clean = []
        for point in points[:100]:
            if (isinstance(point, dict) and type(point.get("ms")) is int
                    and 0 <= point["ms"] <= 86400000):
                note = point.get("note", "")
                clean.append({"ms": point["ms"], "note": str(note)[:100]})
        if clean:
            result[key] = sorted(clean, key=lambda m: m["ms"])
    return result
