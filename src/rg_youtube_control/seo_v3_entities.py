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


def prune_unverified_description_sentences(
    draft: dict[str, Any],
    complete_source: list[dict[str, Any]],
    ledger: dict[str, Any],
    *,
    minimum: int = 400,
) -> tuple[dict[str, Any], int]:
    """Remove entire ungrounded-name sentences only if a valid full description survives.

    This is intentionally NOT string replacement, translation, or a new
    assertion. It never turns an unsupported name into a guessed identity.
    All retained sentences preserve their original exact source citations.
    The independent reviewer must still audit the complete revised SEO.
    """
    from copy import deepcopy
    from .seo_v3_fields import check_sentence_provenance
    from .seo_v3_numbers import check_cited_numbers
    from .seo_v3_claims import check_claim_type_constraints

    rows = draft.get("sentence_provenance")
    if not isinstance(rows, list) or len(rows) < 2:
        return draft, 0
    kept: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            return draft, 0
        sentence = str(row.get("text") or "").strip()
        ids = row.get("evidence_ids")
        if not sentence or not isinstance(ids, list) or not ids:
            return draft, 0
        if unsupported_names_v3({"description": sentence}, complete_source):
            continue
        kept.append({"text": sentence, "evidence_ids": list(ids)})
    removed = len(rows) - len(kept)
    if not removed or not kept:
        return draft, 0
    new_description = " ".join(row["text"] for row in kept)
    if not minimum <= len(new_description) <= 900:
        return draft, 0
    revised = deepcopy(draft)
    revised["description"] = new_description
    revised["sentence_provenance"] = kept
    revised.setdefault("support_ids", {})["description"] = list(dict.fromkeys(
        eid for row in kept for eid in row["evidence_ids"]
    ))
    if (check_sentence_provenance(revised, ledger)
            or any(issue.get("field") == "description"
                   for issue in check_cited_numbers(revised, ledger))
            or any(issue.get("field") == "description"
                   for issue in check_claim_type_constraints(revised, ledger))
            or unsupported_names_v3({"description": new_description}, complete_source)):
        return draft, 0
    return revised, removed
