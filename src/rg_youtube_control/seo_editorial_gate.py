"""Conservative source-grounded editorial flags; never an approval engine.

Only flags mechanically verifiable defects. Absence of flags is NOT approval.
"""
from __future__ import annotations

import re
from typing import Any

_MIXED_RUSSIAN = re.compile(
    r"(?<![\w])(?:увольнення|увольн(?:ение|ения)|неудобненькая|"
    r"неудобн(?:ый|ая|ые)|россия|россии|говорят|коррупция|"
    r"почему|война|вопросы|жизнь|должность|путин)(?![\w])",
    re.IGNORECASE,
)
_NON_UKRAINIAN = re.compile(r"[ыэъё]", re.IGNORECASE)
_STOP = {
    "і", "та", "у", "в", "із", "з", "на", "про", "як", "що", "чи", "де", "за",
    "для", "до", "від", "після", "його", "її", "вони", "їх", "чому", "коли",
    "який", "яка", "які", "але", "це", "росіяни", "росіянин",
    "чат", "рулетка", "гудбай", "раша",
}


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[а-яіїєґa-z0-9]+", value.casefold())
        if len(token) >= 4 and token not in _STOP
    }


def _overlap(a: str, b: str) -> float:
    left = _tokens(a)
    right = _tokens(b)
    if min(len(left), len(right)) < 2:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _substantive_bigrams(value: str) -> set[str]:
    """Extract unusual word pairs, ignoring common channel-format phrases."""
    words = re.findall(r"[а-яіїєґa-z0-9]+", value.casefold())
    pairs = set()
    for a, b in zip(words, words[1:]):
        if len(a) < 3 or len(b) < 3:
            continue
        if a in _STOP or b in _STOP:
            # Keep short possessive+rare noun ("мій цар") as a quoted hook.
            if a not in {"мій", "моя", "мої", "наш", "його"}:
                continue
        if (a, b) in {("чат","рулетка"),("раша","гудбай")}:
            continue
        pairs.add(a + " " + b)
    return pairs


def editorial_risk_flags(package: dict[str, Any], transcript: str) -> list[str]:
    """Return deterministic red flags, not a factuality verdict."""
    title = str(package.get("title") or "")
    variants = [str(x) for x in package.get("title_variants") or []]
    desc = str(package.get("description") or "")
    source = str(transcript or "").casefold()
    flags = []
    fields = [("title", title), *[(f"ab_{i}", v) for i,v in enumerate(variants, 1)], ("description", desc)]
    for label, value in fields:
        if _NON_UKRAINIAN.search(value) or _MIXED_RUSSIAN.search(value):
            flags.append(f"MIXED_LANGUAGE:{label}")
    # Strong case: source explicitly mentions buying a house, not an apartment;
    # do not silently change the object in a marketing headline.
    # Timestamped captions split grammatical phrases across [mm:ss] markers.
    normalized_source = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]", " ", source)
    normalized_source = " ".join(normalized_source.split())
    source_has_house_purchase = bool(re.search(
        r"(?:купил\w*|придбал\w*)\s+(?:\w+\s+){0,3}дом\b",
        normalized_source,
    ))
    source_has_apartment_purchase = bool(re.search(
        r"(?:купил\w*|придбал\w*)\s+(?:\w+\s+){0,3}(?:квартир\w*|помешканн\w*)",
        normalized_source,
    ))
    seo_uses_apartment = any(re.search(
        r"квартир\w*|помешканн\w*", value, re.IGNORECASE
    ) for _, value in fields)
    seo_uses_house = any(re.search(
        r"будин\w*|дом\b", value, re.IGNORECASE
    ) for _, value in fields)
    if source_has_house_purchase and seo_uses_apartment:
        if source_has_apartment_purchase:
            # The same source mentions both property types. Do not guess
            # whether they refer to one transaction or separate statements.
            flags.append("PROPERTY_TYPE_AMBIGUITY:VERIFY_CONTEXT")
        else:
            flags.append("UNSUPPORTED_APARTMENT:VERIFY_SOURCE")
    if source_has_apartment_purchase and seo_uses_house and not source_has_house_purchase:
        flags.append("UNSUPPORTED_HOUSE:VERIFY_SOURCE")
    for i, value in enumerate(variants):
        for j in range(i+1, len(variants)):
            lexical_overlap = _overlap(value, variants[j])
            repeated_hook = _substantive_bigrams(value) & _substantive_bigrams(variants[j])
            if lexical_overlap >= 0.7 or repeated_hook:
                flags.append(f"REPEATED_AB_ANGLE:{i+1}:{j+1}")
    return sorted(set(flags))