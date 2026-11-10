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
    diagnostics: dict[str, list[str]] | None = None,
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

    def format_defects(report: dict[str, Any], field: str) -> list[str]:
        found: list[str] = []
        for section in ("format", "editorial"):
            info = report.get(section) or {}
            details = info.get("problems" if section == "format" else "issues")
            if isinstance(details, dict):
                issue_list = details.get(field) or []
                found.extend(str(issue) for issue in issue_list)
        return list(dict.fromkeys(found))

    # A syntactically valid independent review can overlook obvious format
    # problems. Feed those into the same strict field-level correction loop.
    for field in priority:
        if format_defects(current_gate, field):
            pending.add(field)

    for field in priority[:max_fields]:
        # Carry new reviewer concerns forward after each successful edit;
        # a revision may expose a previously hidden unsupported claim.
        field_issues = [
            issue for issue in current_review.get("issues") or []
            if isinstance(issue, dict) and issue.get("field") == field
        ]
        for defect in format_defects(current_gate, field):
            field_issues.append({
                "field": field,
                "reason": (
                    "MANDATORY EDITORIAL FORMAT REQUIREMENT FAILED: "
                    + defect + ". Repair only this field, using verified "
                      "source quotations; never fabricate topical tags."
                ),
            })
        if field not in pending and not field_issues:
            continue
        attempts = []
        for attempt_number in range(2):
            relevant = {"issues": list(field_issues)}
            if not relevant["issues"]:
                break
            try:
                revised = revise_semantic_defects(
                    candidate, proof, relevant, writer,
                )
            except (ValueError, TypeError, RuntimeError, TimeoutError):
                revised = None
            if revised is None or revised.get(field) == candidate.get(field):
                attempts.append("NO_USABLE_FIELD_REVISION")
                field_issues.append({
                    "field": field,
                    "reason": "Previous answer was unchanged or invalid. "
                              "Return a valid correction for this field with "
                              "verifiable source IDs, or leave it blocked.",
                })
                continue
            # Never let a targeted edit modify another SEO field or its
            # evidence pointers.
            old_support = candidate.get("support_ids") or {}
            new_support = revised.get("support_ids") or {}
            if (any(revised.get(other) != candidate.get(other)
                    for other in priority if other != field)
                    or any(new_support.get(other) != old_support.get(other)
                           for other in priority if other != field)):
                attempts.append("OTHER_FIELD_CHANGED")
                field_issues.append({
                    "field": field,
                    "reason": "Your previous response changed a different SEO "
                              "field. Edit only the requested field.",
                })
                continue
            new_gate = validate(revised)
            new_gate_issues = set(new_gate.get("issues") or [])
            old_gate_issues = set(current_gate.get("issues") or [])
            remaining_format = format_defects(new_gate, field)
            # Independently grounded shorter text is safer than retaining
            # a factually false padded description. This NEVER clears the
            # final editorial format gate or authorizes publication.
            allow_short_description_partial = (
                field == "description"
                and bool(remaining_format)
                and set(remaining_format).issubset({
                    "DESCRIPTION_UNDER_EDITORIAL_TARGET", "SHORT",
                })
                and len(str(revised.get("description") or "")) >= 160
            )
            if remaining_format and not allow_short_description_partial:
                attempts.append("FIELD_FORMAT_STILL_INVALID")
                field_issues.append({
                    "field": field,
                    "reason": "Field still fails the mandatory format: "
                              + ", ".join(remaining_format)
                              + ". For descriptions, write 420-650 supported "
                                "Ukrainian characters with attributed claims. "
                                "For tags, return 8-15 DISTINCT verified phrases.",
                })
                continue
            if (new_gate_issues - old_gate_issues
                    and not (
                        allow_short_description_partial
                        and (new_gate_issues - old_gate_issues).issubset({
                            "EDITORIAL_GATE_FAILED", "FORMAT_GATE_FAILED"
                        })
                    )):
                attempts.append("NEW_TECHNICAL_ISSUE")
                field_issues.append({
                    "field": field,
                    "reason": "Last correction created technical validation "
                              "errors: " + ", ".join(
                                  sorted(new_gate_issues - old_gate_issues)),
                })
                continue
            def names_in_field(obj: dict[str, Any]) -> set[str]:
                isolated = {
                    "title": "", "description": "",
                    "title_variants": [], "tags": [],
                }
                isolated[field] = obj.get(field)
                return set(unsupported_names(isolated, proof))
            remaining_names = names_in_field(revised)
            if remaining_names:
                attempts.append("UNVERIFIED_NAME_REMAINS")
                field_issues.append({
                    "field": field,
                    "reason": "Unverified source-name spelling still present: "
                              + ", ".join(sorted(remaining_names))
                              + ". Remove these specific names; use a verified "
                                "role or neutral subject without inventing an "
                                "identity. Other fields must remain unchanged.",
                })
                continue
            if set(unsupported_names(revised, proof)) - set(
                unsupported_names(candidate, proof)
            ):
                attempts.append("NEW_UNVERIFIED_NAME")
                continue
            try:
                checked = independent_review(revised, proof, reviewer)
            except (ValueError, TypeError, RuntimeError, TimeoutError):
                checked = {"issues": [{
                    "field": "reviewer",
                    "reason": "SECOND_REVIEW_UNAVAILABLE",
                }]}
            after_fields = {
                str(item.get("field"))
                for item in checked.get("issues") or []
                if isinstance(item, dict)
            }
            if field in after_fields or "reviewer" in after_fields:
                attempts.append("INDEPENDENT_REVIEW_REJECTED")
                field_issues = [
                    item for item in checked.get("issues") or []
                    if isinstance(item, dict) and item.get("field") == field
                ]
                if not field_issues:
                    field_issues = [{
                        "field": field,
                        "reason": "The independent reviewer could not verify "
                                  "the proposed correction.",
                    }]
                continue
            candidate, current_gate, current_review = revised, new_gate, checked
            changed.append(field)
            attempts.append(
                "SAFE_PARTIAL_REVIEW_REQUIRED" if remaining_format
                else "ACCEPTED"
            )
            break
        if diagnostics is not None:
            diagnostics[field] = attempts
    return candidate, current_gate, current_review, changed
