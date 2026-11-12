"""Conservative per-field and per-sentence numerical provenance guard.

A numeral somewhere in the transcript does not support its use in an
unrelated headline, tag or description sentence. This is a mechanical
source check, not an assertion that the spoken number is externally true.
"""
from __future__ import annotations

import re
from typing import Any

NUMERAL = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)")


def _numbers(text: Any) -> set[str]:
    return {m.group().replace(",", ".") for m in NUMERAL.finditer(str(text or ""))}


def check_cited_numbers(
    draft: dict[str, Any], ledger: dict[str, Any]
) -> list[dict[str, str]]:
    """Reject numbers missing from the literal source quotes cited per field.

    Uncited IDs also fail closed. Number strings are compared exactly after
    decimal separator normalization. No claim is treated as proven truth.
    """
    claims = {
        str(c["claim_id"]): str(c.get("source_quote") or "")
        for c in ledger.get("claims", [])
        if isinstance(c, dict) and c.get("claim_id")
    }
    support = draft.get("support_ids") or {}
    if not isinstance(support, dict):
        support = {}
    findings: list[dict[str, str]] = []

    def inspect(field: str, text: str, ids: Any) -> None:
        numbers = _numbers(text)
        if not numbers:
            return
        if not isinstance(ids, list) or not ids or any(
            not isinstance(eid, str) or eid not in claims for eid in ids
        ):
            findings.append({"field": field, "reason": "NUMBER_SOURCE_IDS_INVALID"})
            return
        sourced = set().union(*(_numbers(claims[eid]) for eid in ids))
        for number in sorted(numbers - sourced):
            findings.append({
                "field": field,
                "reason": "NUMBER_NOT_IN_CITED_QUOTES:" + number,
            })

    inspect("title", str(draft.get("title") or ""), support.get("title"))
    for field in ("title_variants", "tags"):
        texts = draft.get(field) or []
        groups = support.get(field) or []
        if not isinstance(texts, list):
            continue
        for i, item in enumerate(texts):
            ids = groups[i] if isinstance(groups, list) and i < len(groups) else None
            inspect(field, str(item), ids)

    # Description requires evidence per sentence, rather than a pooled
    # field-level citation list that could conceal unrelated numbers.
    sentences = draft.get("sentence_provenance")
    if isinstance(sentences, list):
        for row in sentences:
            if isinstance(row, dict):
                inspect(
                    "description",
                    str(row.get("text") or ""),
                    row.get("evidence_ids"),
                )
    elif _numbers(draft.get("description")):
        findings.append({
            "field": "description",
            "reason": "NUMBER_SENTENCE_PROVENANCE_MISSING",
        })
    return findings
