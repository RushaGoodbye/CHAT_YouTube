"""One bounded, source-grounded correction pass for each failed SEO v3 field.

This module never treats citations as proof of a claim. No approval or
publishing can occur here. A changed field survives only if it passes a fresh,
independent claim-type audit and the available deterministic source gates.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Callable

from .seo_v3_entities import unsupported_names_v3 as unsupported_names
from .seo_v3_claims import check_claim_type_constraints
from .seo_v3_fields import check_sentence_provenance


FIELDS = ("title", "title_variants", "description", "tags")


def _field_names(draft: dict[str, Any], field: str, proof: list[dict[str, Any]]) -> list[str]:
    subset = {"title": "", "title_variants": [], "description": "", "tags": []}
    subset[field] = draft.get(field)
    return unsupported_names(subset, proof)


def _ids_valid(draft: dict[str, Any], field: str, allowed: set[str]) -> bool:
    support = (draft.get("support_ids") or {}).get(field)
    values = draft.get(field)
    if field in ("title", "description"):
        return isinstance(values, str) and bool(values.strip()) and isinstance(support, list) and bool(support) and all(
            isinstance(eid, str) and eid in allowed for eid in support
        )
    return (
        isinstance(values, list) and bool(values)
        and all(isinstance(value, str) and bool(value.strip()) for value in values)
        and isinstance(support, list) and len(support) == len(values)
        and all(isinstance(group, list) and bool(group)
                and all(isinstance(eid, str) and eid in allowed for eid in group)
                for group in support)
    )


def _field_format_issues(gate: dict[str, Any], field: str) -> list[str]:
    result: list[str] = []
    for kind, prop in (("format", "problems"), ("editorial", "issues")):
        details = (gate.get(kind) or {}).get(prop) or {}
        if isinstance(details, dict):
            result.extend(str(item) for item in details.get(field) or [])
    return list(dict.fromkeys(result))


def repair_claim_fields(
    draft: dict[str, Any],
    claim_ledger: dict[str, Any],
    proof: list[dict[str, Any]],
    initial_review: dict[str, Any],
    writer: Callable[[str], dict[str, Any]],
    reviewer: Callable[[dict[str, Any]], dict[str, Any]],
    gate_check: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    max_fields: int = 4,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    """Repair each failed field once. Reject any unsafe/unsupported revision.

    Other fields remain unchanged. A short description can only be retained
    if it is source-audited and improves factual accuracy; the editorial gate
    must still fail until it is long enough.
    """
    candidate = deepcopy(draft)
    current_review = initial_review
    current_gate = gate_check(candidate)
    diagnostics: dict[str, str] = {}
    allowed = {str(c["claim_id"]) for c in claim_ledger["claims"]}
    indexed = {str(c["claim_id"]): c for c in claim_ledger["claims"]}
    if initial_review.get("review_status") == "FAILED_CLOSED":
        return candidate, current_gate, current_review, {"reviewer": "FAILED_CLOSED"}
    for field in FIELDS[:max_fields]:
        reasons = [
            str(issue.get("reason") or "")
            for issue in (current_review.get("issues") or [])
            if isinstance(issue, dict) and issue.get("field") == field
        ]
        reasons.extend(_field_format_issues(current_gate, field))
        # Deterministic source gates are independent of the LLM reviewer.
        # Include their field-specific failures in the bounded repair task,
        # even when the reviewer returns an empty list of issues.
        reasons.extend(
            str(issue.get("reason") or "")
            for issue in check_claim_type_constraints(candidate, claim_ledger)
            if issue.get("field") == field
        )
        from .seo_v3_numbers import check_cited_numbers
        reasons.extend(
            str(issue.get("reason") or "")
            for issue in check_cited_numbers(candidate, claim_ledger)
            if issue.get("field") == field
        )
        invalid_names = _field_names(candidate, field, proof)
        if invalid_names:
            reasons.append("Unverified name spellings: " + ", ".join(invalid_names))
        if not reasons:
            continue
        banned_names = invalid_names
        # The editor must see the quotations underlying this field first,
        # followed by a limited set of nearby alternative source quotes.
        # Sending the full 24-claim ledger encouraged unrelated names and
        # quantities in title/tag repairs. We preserve every original ID
        # and still run the full ledger through all validation gates.
        field_support = (candidate.get("support_ids") or {}).get(field)
        cited_ids: set[str] = set()
        if isinstance(field_support, list):
            for group in field_support:
                if isinstance(group, str):
                    cited_ids.add(group)
                elif isinstance(group, list):
                    cited_ids.update(eid for eid in group if isinstance(eid, str))
        cited_claims = [
            claim for claim in indexed.values()
            if claim["claim_id"] in cited_ids
        ]
        alternative_claims = [
            claim for claim in indexed.values()
            if claim["claim_id"] not in cited_ids
        ]
        # Descriptions need more independent claims than headlines.
        claim_budget = 14 if field == "description" else 10
        claims_for_field = (
            cited_claims[:claim_budget]
            + alternative_claims[:max(0, claim_budget - len(cited_claims))]
        )
        prompt = (
            "You are a Ukrainian SEO source-faithfulness correction editor. "
            "Fix ONLY the requested field, ONCE. All facts must come from "
            "SOURCE-TYPED CLAIMS. QUESTION is unanswered, CONDITIONAL is "
            "hypothetical, HYPOTHESIS is a speaker's suggestion, and "
            "SPEAKER_STATEMENT is attributed speech, not independently "
            "verified truth. Remove uncertain proper names completely; "
            "never guess an identity. Remove digits not present in the "
            "exact cited source quotation; do not invent or convert "
            "unsupported numeric quantities. Do not assert real causes, known "
            "motivations or confirmed punishment from these sources. "
            "Description must have 400-900 meaningful source-supported "
            "Ukrainian characters, preferably 5-7 attributed sentences; "
            "do not pad or invent to reach the target. Tags must be 8-15 "
            "distinct subject phrases, not claims of hypothetical outcomes. "
            "Title variants must be exactly three. "
            "Do NOT answer a question from a QUESTION citation. A question "
            "about an alleged real cause only supports a question ABOUT "
            "that cause, not a keyword asserting a real cause exists. "
            "When revising tags, keep 8-15 distinct, specific neutral "
            "SUBJECT phrases, not outcomes or unsupported motives. "
            "Keep already safe tags and their matching evidence IDs; "
            "replace rejected tags only, and avoid unrelated tangents. "
            "When revising titles, preserve the PRIMARY topic and replace "
            "unsupported certainty with a concise attributed discussion "
            "or a genuine unanswered question. "
            "When revising a short description, write 7-8 DIFFERENT "
            "source-cited sentences about relevant discussion points "
            "using 400-900 Ukrainian characters in total. Reuse source "
            "IDs across distinct aspects only if the literal quote "
            "supports those aspects; never fabricate a new event. "
            "For each sentence preserve the cited source type explicitly: "
            "QUESTION -> 'ведучий запитує ...', SPEAKER_STATEMENT -> "
            "'співрозмовник пояснив ...', HYPOTHESIS -> "
            "'учасник припускає ...', CONDITIONAL -> 'якщо ...'. "
            "Never turn an attributed viewpoint into independently "
            "verified news. For every sentence supply its complete text "
            "and its exact IDs. "
            "Return ONLY JSON object with keys 'value' and 'evidence_ids'. "
            "For title and description: value is a string and evidence_ids "
            "is an array of source IDs; for DESCRIPTION additionally return "
            "sentences: an array of {text, evidence_ids} with each complete "
            "sentence and its exact claim IDs, in original order. "
            "The joined sentence texts MUST equal value exactly. "
            "For title_variants and tags: value "
            "is a list of strings and evidence_ids is the same-length "
            "list of arrays. If no safe edit is possible, return "
            "{\\\"value\\\":null,\\\"evidence_ids\\\":null}. "
            "No other fields.\nFIELD: " + field
            + "\nCURRENT FIELD: " + json.dumps(candidate.get(field), ensure_ascii=False)
            + "\nCURRENT EVIDENCE IDS: " + json.dumps(field_support, ensure_ascii=False)
            + "\nEXACT EDITOR REJECTIONS: " + json.dumps(reasons, ensure_ascii=False)
            + "\nUNVERIFIED NAMES TO REMOVE: " + json.dumps(banned_names, ensure_ascii=False)
            + "\nSOURCE-TYPED CLAIMS: " + json.dumps(claims_for_field, ensure_ascii=False)
        )
        try:
            result = writer(prompt)
            if isinstance(result, str):
                result = json.loads(result)
        except (ValueError, TypeError, RuntimeError, TimeoutError):
            result = None
        if not isinstance(result, dict):
            diagnostics[field] = "INVALID_REVISION_RESPONSE"
            continue
        new_value, new_support = result.get("value"), result.get("evidence_ids")
        if new_value is None:
            diagnostics[field] = "NO_SAFE_REVISION"
            continue
        if field == "description" and isinstance(new_value, str):
            # The sentences, not a second model-written summary, are the
            # source of truth for the revised description. Deterministically
            # concatenate each individually cited sentence in given order.
            # Every sentence is then checked for modality and source IDs,
            # and the COMPLETE revised field must pass a fresh independent
            # audit. Never use a discarded summary as evidence.
            rows = result.get("sentences")
            if isinstance(rows, list) and rows and all(
                isinstance(row, dict)
                and isinstance(row.get("text"), str)
                and bool(row["text"].strip())
                for row in rows
            ):
                new_value = " ".join(str(row["text"]).strip() for row in rows)
                ordered_support = list(dict.fromkeys(
                    eid for row in rows
                    for eid in (row.get("evidence_ids") or [])
                    if isinstance(eid, str)
                ))
                # Do not blindly accept a global support list mismatched
                # against individual sentence citations.
                if (isinstance(new_support, list)
                        and set(new_support) == set(ordered_support)):
                    new_support = ordered_support
        revised = deepcopy(candidate)
        revised[field] = new_value
        revised.setdefault("support_ids", {})[field] = new_support
        if field == "description":
            # The old provenance MUST NOT survive a description rewrite.
            # Require independently supplied per-sentence exact citations.
            revised["sentence_provenance"] = result.get("sentences")
            problems = check_sentence_provenance(revised, claim_ledger)
            if problems:
                # Emit a precise, fixed-code diagnostic only, never the
                # private sentence or SRT text.
                reason = str(problems[0].get("reason") or "UNKNOWN")
                diagnostics[field] = "DESCRIPTION_PROVENANCE_INVALID:" + reason
                continue
        if not _ids_valid(revised, field, allowed):
            diagnostics[field] = "SOURCE_LINKS_OR_SHAPE_INVALID"
            continue
        if revised[field] == candidate[field] and new_support == field_support:
            diagnostics[field] = "UNCHANGED"
            continue
        if _field_names(revised, field, proof):
            diagnostics[field] = "UNVERIFIED_NAME_REMAINS"
            continue
        violations = [item for item in check_claim_type_constraints(revised, claim_ledger)
                      if item.get("field") == field]
        if violations:
            diagnostics[field] = "CLAIM_MODALITY_FAILED"
            continue
        new_gate = gate_check(revised)
        # Compare the edited field, not stale global flags. The initial
        # global gate can omit name warnings that are injected later by
        # source-level checks; that omission must not block an unrelated,
        # independently verified tag/description correction.
        old_field_issues = set(_field_format_issues(current_gate, field))
        new_field_issues = set(_field_format_issues(new_gate, field))
        if new_field_issues - old_field_issues:
            diagnostics[field] = "NEW_FIELD_FORMAT_FAILURE"
            continue
        # Keep existing successful unrelated fields unchanged.
        if any(revised.get(other) != candidate.get(other) or
               (revised.get("support_ids") or {}).get(other) !=
               (candidate.get("support_ids") or {}).get(other)
               for other in FIELDS if other != field):
            diagnostics[field] = "UNRELATED_FIELD_CHANGED"
            continue
        try:
            checked = reviewer(revised)
        except (ValueError, TypeError, RuntimeError, TimeoutError):
            checked = {"review_status": "FAILED_CLOSED",
                       "issues": [{"field": "reviewer", "reason": "UNAVAILABLE"}]}
        remaining_fields = {
            str(item.get("field")) for item in checked.get("issues") or []
            if isinstance(item, dict)
        }
        if field in remaining_fields or "reviewer" in remaining_fields or (
            checked.get("review_status") == "FAILED_CLOSED"
        ):
            diagnostics[field] = "INDEPENDENT_REVIEW_REJECTED"
            continue
        if _field_format_issues(new_gate, field):
            diagnostics[field] = "FIELD_FORMAT_STILL_INVALID"
            continue
        candidate, current_gate, current_review = revised, new_gate, checked
        diagnostics[field] = "ACCEPTED"
    return candidate, current_gate, current_review, diagnostics
