"""SEO v3 proper-noun grounding for mixed Russian/Ukrainian ASR.

Personal names remain strict. Locative forms can be accepted from
verbatim Russian-language location mentions without a fixed gazetteer.
"""
from __future__ import annotations

import re
from typing import Any

from .seo_v2_semantic import unsupported_names, _name_key


def _canonical(token: str) -> str:
    # Russian spelling has double consonants and different case endings.
    value = _name_key(token).casefold().replace("ь", "").replace("ъ", "")
    return re.sub(r"(.)\1+", r"\1", value)


def _locative_context(text: str, name: str) -> bool:
    pat = re.compile(
        r"(?i)(?<!\w)(?:у|в|на|до|із|з|від|по|для|між|біля|"
        r"поблизу|стосовно)\s+"
        + re.escape(name) + r"(?=\b|[-–—])"
    )
    return pat.search(text) is not None


def unsupported_names_v3(
    draft: dict[str, Any], complete_source: list[dict[str, Any]],
) -> list[str]:
    """Safely reduce false location-name alerts, never guess a person.

    This does NOT verify real-world geography or promote the source to fact.
    It only checks a Ukrainian locative spelling against corresponding raw
    source words. A short accidental prefix is insufficient for long words.
    """
    unsupported = unsupported_names(draft, complete_source)
    raw_words = [
        _canonical(word)
        for row in complete_source
        for word in re.findall(
            r"[А-ЯҐЄІЇа-яґєіїЁёЭэЫыЪъ]{3,}",
            str(row.get("quote") or ""),
        )
    ]
    fields = [
        str(draft.get("title") or ""),
        str(draft.get("description") or ""),
        *[str(x) for x in draft.get("title_variants") or []],
        *[str(x) for x in draft.get("tags") or []],
    ]
    still_unverified = []
    for name in unsupported:
        # Only waive the SPELLING alarm for a word in an actual locative
        # phrase, and only when there is a strong lexical source root.
        if not any(_locative_context(field, name) for field in fields):
            still_unverified.append(name)
            continue
        stem = _canonical(name)
        # Four-letter exact stems cover forms like Росії / России;
        # fuzzy locative matching still needs a seven-letter source root.
        match = any(
            len(stem) >= 4 and len(word) >= 4
            and (
                stem == word
                or (min(len(stem), len(word)) >= 7
                    and stem[:6] == word[:6])
            )
            for word in raw_words
        )
        if not match:
            still_unverified.append(name)
    return still_unverified
