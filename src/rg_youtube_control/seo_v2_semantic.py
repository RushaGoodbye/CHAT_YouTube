"""Generic semantic safety checks and bounded editorial revision for SEO v2.

Checks never claim to verify the truth of a spoken opinion. The deterministic
name check only prevents confident publication of names missing from the
literal quoted evidence. Review-based changes remain human-review-only.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Callable

from .seo_quality_gate import language_error


def _words(text: str) -> list[str]:
    return re.findall(r"[А-ЯҐЄІЇа-яґєіїЁёЭэЫыЪъ]+", text)


def _name_key(value: str) -> str:
    """Compare UA/RU writing conventions without guessing name identity."""
    return value.casefold().translate(str.maketrans({
        "і": "и", "ї": "и", "є": "е", "ґ": "г", "ё": "е",
    }))


def _same_inflected_name(name: str, source: str) -> bool:
    """Accept only near-identical source forms or short case suffixes."""
    left, right = _name_key(name), _name_key(source)
    if left == right:
        return True
    if min(len(left), len(right)) >= 5:
        shorter, longer = sorted((left, right), key=len)
        if len(longer) - len(shorter) <= 2 and longer.startswith(shorter):
            return True
    if (len(left) == len(right) and len(left) >= 5
            and left[:-1] == right[:-1]
            and left[-1] in "аеиоуыюяь"
            and right[-1] in "аеиоуыюяь"):
        return True
    if min(len(left), len(right)) >= 7 and abs(len(left) - len(right)) <= 2:
        return left[:-2] == right[:-2]
    return False


def unsupported_names(
    draft: dict[str, Any], proof: list[dict[str, Any]],
) -> list[str]:
    """Conservative named-person spell check against cited source quotes.

    In the middle of a sentence, capitalized Cyrillic names must share
    more than a short coincidental prefix with a spoken source word.
    Uncertain ASR spelling blocks acceptance instead of being auto-corrected.
    """
    source = [word.casefold() for row in proof
              for word in _words(str(row.get("quote") or ""))]
    if not source:
        return []
    fields = [
        str(draft.get("title") or ""),
        str(draft.get("description") or ""),
        *[str(v) for v in draft.get("title_variants") or []],
        *[str(v) for v in draft.get("tags") or []],
    ]
    mismatches: set[str] = set()
    for text in fields:
        for match in re.finditer(r"(?<!\w)[А-ЯҐЄІЇЁЭЫ][а-яґєіїёэыъь]{4,}(?!\w)", text):
            name = match.group()
            # Sentence-initial capitals can be common nouns; do not classify.
            prefix = text[:match.start()].rstrip()
            if not prefix or prefix.endswith((".", "!", "?", ":", "\n")):
                continue
            if any(_same_inflected_name(name, item) for item in source):
                continue
            mismatches.add(name)
    return sorted(mismatches)


def _review_prompt(draft: dict[str, Any], proof: list[dict[str, Any]]) -> str:
    return (
        "You are an INDEPENDENT Ukrainian SEO fact-checking editor. "
        "Audit each individual title, A/B variant, description sentence "
        "and tag against the verbatim source quotations, not against "
        "the draft's claims. Identify ALL uncertain personal names "
        "(including misspelled names caused by ASR), inferred motives, "
        "unproven causality and opinions rewritten as objective facts. "
        "A spoken speculation must remain attributed and tentative. "
        "If the quote is a question, do NOT turn it into an answer. "
        "Check source relevance, numbers, Ukrainian grammar and fabricated "
        "connections between separate quotes. Be strict and concise. "
        "Return ONLY {\"issues\":[{\"field\":\"title|title_variants|description|tags\","
        "\"reason\":\"specific defect with quote ID\"}]}. "
        "An empty issues list is only appropriate if ALL phrases are fully "
        "supported. You cannot approve publication.\nDRAFT:\n"
        + json.dumps(draft, ensure_ascii=False)
        + "\nVERBATIM EVIDENCE:\n"
        + json.dumps(proof, ensure_ascii=False)
    )


def independent_review(
    draft: dict[str, Any], proof: list[dict[str, Any]],
    reviewer: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    result = reviewer(_review_prompt(draft, proof))
    if isinstance(result, str):
        result = json.loads(result)
    issues = result.get("issues") if isinstance(result, dict) else None
    if not isinstance(issues, list) or any(
        not isinstance(item, dict)
        or not str(item.get("field") or "").strip()
        or not str(item.get("reason") or "").strip()
        for item in issues
    ):
        return {"issues": [{
            "field": "reviewer",
            "reason": "INVALID_INDEPENDENT_REVIEW_SCHEMA",
        }], "review_status": "FAILED_CLOSED"}
    return {"issues": issues}


def revise_semantic_defects(
    draft: dict[str, Any], proof: list[dict[str, Any]],
    review: dict[str, Any], writer: Callable[[str], dict[str, Any]],
) -> dict[str, Any] | None:
    """Exactly one focused repair request, never a change to unrelated fields.

    The caller re-runs all deterministic gates and a *fresh* independent
    review before accepting this candidate.
    """
    issues = review.get("issues") or []
    allowed_fields = {"title", "description", "title_variants", "tags"}
    fields = sorted({
        str(item.get("field"))
        for item in issues if isinstance(item, dict)
        and str(item.get("field")) in allowed_fields
    })
    if not fields:
        return None
    allowed_ids = {row["evidence_id"] for row in proof}
    prompt = (
        "You are correcting ONLY factual and linguistic defects identified "
        "by an independent reviewer. No new facts, no inferred motivation "
        "or causality, no misattributed claims, no unverified name spelling. "
        "Keep opinions attributed to the speaker. Preserve EVERY OTHER "
        "SEO field exactly unchanged. Do not pad tags with generic phrases. "
        "Return JSON with key 'changes' containing ONLY these field names: "
        + json.dumps(fields, ensure_ascii=False)
        + ". Each value MUST match the existing field type: title/description "
        "as string, title_variants/tags as arrays of text. "
        "Additionally return 'support_ids' containing citation ID arrays "
        "ONLY for the modified fields, in the same structure as the draft. "
        "If an issue cannot be corrected from the quotes, do not change "
        "that field. Do not return any fields outside 'changes' and "
        "'support_ids'.\nREVIEWER DEFECTS:\n"
        + json.dumps(issues, ensure_ascii=False)
        + "\nCURRENT DRAFT:\n" + json.dumps(draft, ensure_ascii=False)
        + "\nLITERAL QUOTES:\n" + json.dumps(proof, ensure_ascii=False)
    )
    raw = writer(prompt)
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        return None
    changes, citations = raw.get("changes"), raw.get("support_ids")
    if not isinstance(changes, dict) or not isinstance(citations, dict):
        return None
    if not changes or any(k not in fields for k in changes):
        return None
    candidate = deepcopy(draft)
    support = candidate.setdefault("support_ids", {})
    if not isinstance(support, dict):
        return None
    for field, value in changes.items():
        existing = candidate.get(field)
        if not isinstance(value, type(existing)) or isinstance(value, bool):
            return None
        if field in {"title_variants", "tags"}:
            if not isinstance(value, list) or not all(
                isinstance(v, str) and v.strip() for v in value
            ):
                return None
        elif not isinstance(value, str) or not value.strip():
            return None
        new_ids = citations.get(field)
        if field in {"title", "description"}:
            valid = (
                isinstance(new_ids, list) and bool(new_ids) and
                all(isinstance(i, str) and i in allowed_ids for i in new_ids)
            )
        else:
            valid = (
                isinstance(new_ids, list) and len(new_ids) == len(value)
                and all(isinstance(group, list) and group and
                        all(isinstance(i, str) and i in allowed_ids for i in group)
                        for group in new_ids)
            )
        if not valid:
            return None
        if field in {"title", "description"} and language_error(value):
            return None
        if field in {"title_variants", "tags"} and any(
            language_error(v) for v in value
        ):
            return None
        candidate[field] = value
        support[field] = new_ids
    if candidate == draft:
        return None
    return candidate
