"""Offline, zero-API SEO quality helpers from permissively licensed tools.

RapidFuzz is an existing RG YouTube Control dependency (MIT license).
Keep this deterministic and quote-agnostic: a similarity score can detect
repeated headlines but must NEVER be treated as evidence for a new fact.
"""
from __future__ import annotations

import re
from itertools import combinations
from typing import Iterable

from rapidfuzz import fuzz


_STOP = {
    "що", "чому", "де", "коли", "як", "про", "для", "та", "або",
    "і", "й", "у", "в", "на", "це", "так", "вони", "вона",
    "кажуть", "говорять", "говорили", "сказали", "відповіли",
    "думки", "думка", "думали", "думають", "люди", "людей", "співрозмовники", "учасники",
    "обговорюють", "обговорення", "історія", "розмова",
    "росіяни", "росіян", "російські", "випуск", "відео",
    "чат", "рулетка", "раша", "гудбай",
    "почему", "как", "что", "это", "они", "она",
    "говорят", "рассказывают", "сказали", "обсуждают",
    "россияне", "россиян", "разговор", "видео", "выпуск",
}


def russian_language_signal(title: str) -> bool:
    """Optional Lingua cross-check for confidently Russian-only headlines.

    It is used only as a REVIEW gate, never to generate or translate text.
    In older Python/installer environments, lack of Lingua is safe: the
    mandatory lexical Ukrainian guard still runs.
    """
    value = str(title or "").strip()
    if len(value) < 26 or len(re.findall(r"[а-яіїєґ]", value.casefold())) < 18:
        return False
    # Strong Ukrainian-specific characters are decisive for mixed titles
    # that quote Russian names or Russian-language source fragments.
    if re.search(r"[іїєґ]", value.casefold()):
        return False
    try:
        from lingua import Language, LanguageDetectorBuilder
    except (ImportError, OSError):
        return False
    try:
        # Lazy two-language comparison avoids loading unrelated languages.
        detector = _lingua_detector(Language, LanguageDetectorBuilder)
        values = detector.compute_language_confidence_values(value)
        if len(values) < 2:
            return False
        russian = next(
            (float(v.value) for v in values if v.language == Language.RUSSIAN),
            0.0,
        )
        ukrainian = next(
            (float(v.value) for v in values if v.language == Language.UKRAINIAN),
            0.0,
        )
        return russian >= 0.92 and russian - ukrainian >= 0.60
    except (RuntimeError, ValueError, AttributeError):
        # Optional auxiliary detector may fail on unsupported platforms;
        # mandatory deterministic source-grounding still protects outputs.
        return False


_detector_cache: dict[str, object] = {}


def _lingua_detector(Language, Builder):
    current = _detector_cache.get("ru_uk")
    if current is None:
        current = Builder.from_languages(
            Language.UKRAINIAN, Language.RUSSIAN
        ).build()
        _detector_cache["ru_uk"] = current
    return current


def _event_signature(title: str) -> set[str]:
    """Meaningful short roots; ignore common editorial title scaffolding."""
    canonical = str(title or "").casefold().translate(str.maketrans({
        "і": "и", "ї": "и", "є": "е", "ґ": "г", "ё": "е",
    }))
    words = re.findall(r"[a-zа-я0-9]{4,}", canonical)
    stems = {
        word[:5]
        for word in words
        if word not in _STOP
        and not word.startswith(("рулет", "гудба", "росси", "спивр", "говор"))
    }
    return stems


def repeated_ab_event_pairs(titles: Iterable[str]) -> list[tuple[int, int]]:
    """Detect same event in shuffled words; do not infer source-grounding.

    A shared protagonist or a common country alone is not a duplicate.
    The outer gate also checks raw text similarity and quoted facts.
    """
    items = [str(title or "").strip() for title in titles]
    if len(items) != 3:
        return []
    signatures = [_event_signature(title) for title in items]
    repeated: list[tuple[int, int]] = []
    for left, right in combinations(range(3), 2):
        a, b = signatures[left], signatures[right]
        if len(a) < 2 or len(b) < 2:
            continue
        # Detect identical narrative event roots even when question and
        # adjective wording is shuffled.
        shared = a & b
        if len(shared) < 2:
            continue
        if len(shared) / min(len(a), len(b)) < 0.85:
            continue
        aa = " ".join(sorted(a))
        bb = " ".join(sorted(b))
        if fuzz.token_sort_ratio(aa, bb) >= 86:
            repeated.append((left, right))
    return repeated
