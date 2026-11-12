"""One-pass, field-specific repairs for universal SEO v2.

No hard-coded conversation subjects. Only fields that fail mechanical
editorial checks are retried. Repairs must cite actual visible source IDs.
The independent semantic reviewer still decides human-review readiness.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Callable

from .seo_quality_gate import inspect_editorial_targets, inspect_package, language_error


def _model_object(chat: Callable[[str], dict[str, Any]], instruction: str) -> dict[str, Any]:
    reply = chat(instruction)
    if isinstance(reply, str):
        reply = json.loads(reply)
    if not isinstance(reply, dict):
        raise ValueError("SEO field repair must return JSON object")
    return reply


def _valid_ids(values: Any, allowed: set[str]) -> bool:
    return (isinstance(values, list) and bool(values)
            and all(isinstance(value, str) and value in allowed for value in values))


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", value))


def repair_editorial_fields(
    original: dict[str, Any],
    evidence: list[dict[str, Any]],
    chat: Callable[[str], dict[str, Any]],
    *,
    spoken_numbers: set[str],
) -> tuple[dict[str, Any], list[str]]:
    """Try at most one rewrite of A/B and one rewrite of description.

    Do not invent filler to meet a character target. Reject a replacement
    that introduces unsupported numeric assertions or new format defects.
    """
    draft = deepcopy(original)
    changed: list[str] = []
    ids = {entry["evidence_id"] for entry in evidence}
    source = json.dumps([
        {"id": entry["evidence_id"], "quote": entry["quote"]}
        for entry in evidence
    ], ensure_ascii=False)
    problems = inspect_package(draft)["problems"]
    editorial = inspect_editorial_targets(draft)["issues"]
    if "title_variants" in problems or "title_variants" in editorial:
        prompt = (
            "Fix ONLY the three A/B YouTube headlines. Return exactly 3 "
            "meaningfully different natural Ukrainian titles, each 35-95 "
            "characters. Keep the central subject and claims sourced "
            "ONLY from the literal quotes; no new facts, names, outcomes "
            "or numeric claims. Return JSON with 'variants' as exactly "
            "three objects {text: headline, evidence_ids: [source ID]}. "
            "Do not alter the primary title, description, or tags. "
            "Reject unsupported claims rather than fabricate them.\n"
            "PRIMARY TITLE: " + str(draft.get("title") or "")
            + "\nOLD VARIANTS: "
            + json.dumps(draft.get("title_variants") or [], ensure_ascii=False)
            + "\nVERBATIM EVIDENCE: " + source
        )
        try:
            response = _model_object(chat, prompt)
            rows = response.get("variants")
            if isinstance(rows, list) and len(rows) == 3:
                names = [str(row.get("text") or "").strip()
                         for row in rows if isinstance(row, dict)]
                citations = [row.get("evidence_ids")
                             for row in rows if isinstance(row, dict)]
                if (
                    len(names) == 3
                    and all(35 <= len(text) <= 95 for text in names)
                    and len(set(name.casefold() for name in names)) == 3
                    and str(draft.get("title") or "").strip().casefold()
                        not in {name.casefold() for name in names}
                    and all(not language_error(name) for name in names)
                    and all(_valid_ids(group, ids) for group in citations)
                    and not (_numbers(" ".join(names)) - spoken_numbers)
                ):
                    candidate = deepcopy(draft)
                    candidate["title_variants"] = names
                    support = candidate.setdefault("support_ids", {})
                    support["title_variants"] = citations
                    if "title_variants" not in inspect_package(candidate)["problems"]:
                        draft = candidate
                        changed.append("title_variants")
        except (ValueError, RuntimeError, TypeError, TimeoutError):
            pass

    problems = inspect_package(draft)["problems"]
    editorial = inspect_editorial_targets(draft)["issues"]
    if "description" in problems or "description" in editorial:
        prompt = (
            "Fix ONLY the YouTube description in natural UKRAINIAN. "
            "Write 400-900 meaningful characters, 4-6 connected sentences. "
            "Preserve the real central subject, attribute speakers' opinions "
            "to speakers, do not add generic padding, unrelated topics or "
            "unsourced events, names, outcomes or numbers. "
            "If there is not enough source detail, return an empty "
            "description and leave the video for human review. "
            "Return JSON object {description: text, evidence_ids: [IDs]}. "
            "Do not modify titles or tags.\n"
            "TITLE: " + str(draft.get("title") or "")
            + "\nOLD DESCRIPTION: " + str(draft.get("description") or "")
            + "\nVERBATIM EVIDENCE: " + source
        )
        try:
            response = _model_object(chat, prompt)
            description = str(response.get("description") or "").strip()
            citations = response.get("evidence_ids")
            if (
                400 <= len(description) <= 900
                and not language_error(description)
                and _valid_ids(citations, ids)
                and not (_numbers(description) - spoken_numbers)
            ):
                candidate = deepcopy(draft)
                candidate["description"] = description
                support = candidate.setdefault("support_ids", {})
                support["description"] = citations
                if (
                    "description" not in inspect_editorial_targets(candidate)["issues"]
                    and "description" not in inspect_package(candidate)["problems"]
                ):
                    draft = candidate
                    changed.append("description")
        except (ValueError, RuntimeError, TypeError, TimeoutError):
            pass
    return draft, changed
