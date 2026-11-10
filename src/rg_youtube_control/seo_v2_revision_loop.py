"""Independently validated, field-by-field SEO v2 semantic repairs.

A single flawed tag must not invalidate an otherwise safe title correction.
Each field gets one revision attempt and a fresh independent review. Never
accept an edited field with remaining issues or newly failed source gates.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from .seo_v2_semantic import (
    independent_review, revise_semantic_defects, unsupported_names,
)


def repair_fields_independently(
    draft: dict[str, Any],
    proof: list[dict[str, Any]],
    initial_review: dict[str, Any],
    writer: Callable[[str], dict[str, Any]],
    reviewer: Callable[[str], dict[str, Any]],
    validate: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    max_fields: int = 4,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    """Only accept a change when that field passes all applicable checks.

    Other failing fields remain in the draft/report; human review stays
    required. This prevents all-or-nothing loss of valid partial corrections.
    """
    candidate = deepcopy(draft)
    current_review = initial_review
    current_gate = validate(candidate)
    changed: list[str] = []
    priority = ("title", "title_variants", "description", "tags")
    pending = {
        str(issue.get("field"))
        for issue in initial_review.get("issues") or []
        if isinstance(issue, dict)
    }
    for field in priority[:max_fields]:
        if field not in pending:
            continue
        relevant = {
            "issues": [
                issue for issue in current_review.get("issues") or []
                if isinstance(issue, dict) and issue.get("field") == field
            ],
        }
        if not relevant["issues"]:
            continue
        try:
            revised = revise_semantic_defects(
                candidate, proof, relevant, writer,
            )
        except (ValueError, TypeError, RuntimeError, TimeoutError):
            continue
        if revised is None or revised.get(field) == candidate.get(field):
            continue
        # The one-field edit must not modify other text or citation arrays.
        if any(revised.get(other) != candidate.get(other)
               for other in priority if other != field):
            continue
        old_support = candidate.get("support_ids") or {}
        new_support = revised.get("support_ids") or {}
        if any(new_support.get(other) != old_support.get(other)
               for other in priority if other != field):
            continue
        new_gate = validate(revised)
        old_gate_issues = set(current_gate.get("issues") or [])
        new_gate_issues = set(new_gate.get("issues") or [])
        # Do not accept any new technical gate failure. Existing failures
        # on unrelated fields may stay until their own revision.
        if new_gate_issues - old_gate_issues:
            continue
        if set(unsupported_names(revised, proof)) - set(unsupported_names(candidate, proof)):
            continue
        try:
            checked = independent_review(revised, proof, reviewer)
        except (ValueError, TypeError, RuntimeError, TimeoutError):
            continue
        after_fields = {
            str(item.get("field")) for item in checked.get("issues") or []
            if isinstance(item, dict)
        }
        if field in after_fields or "reviewer" in after_fields:
            continue
        candidate, current_gate, current_review = revised, new_gate, checked
        changed.append(field)
    return candidate, current_gate, current_review, changed
