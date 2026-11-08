"""G2 source-neighborhood numeric risk screen.

Only flags proposed numbers absent from the original local captions. A warning
is a request for editorial review, not proof of hallucination or falsehood.
"""
from __future__ import annotations

import re
from typing import Any

from .seo_spoken_numbers import grounded_number_values


def screen_numeric_claims(packet: dict[str, Any]) -> dict[str, Any]:
    video_id = str(packet.get("video_id") or "")
    rows = packet.get("records") or []
    findings: list[dict[str, Any]] = []
    for item in rows:
        text = str(item.get("proposed_topic") or "") + " " + str(
            item.get("proposed_summary") or "")
        digits = set(re.findall(r"(?<!\w)\d+(?!\w)", text))
        source = str(item.get("source_context") or "")
        original_quote = str(item.get("source_quote") or "")
        supported = grounded_number_values(source + " " + original_quote)
        unexplained = sorted(digits - supported, key=lambda x: (len(x), x))
        if unexplained:
            findings.append({
                "record_id": item.get("id"),
                "video_id": video_id,
                "numbers_not_in_local_source": unexplained,
                "risk_type": "UNSUPPORTED_NUMERIC_DETAIL_NEEDS_REVIEW",
                "editorial_approved": False,
            })
    return {
        "schema": "RG_G2_NUMERIC_RISKS_V1",
        "video_id": video_id,
        "checked": len(rows),
        "flagged": len(findings),
        "findings": findings,
        "human_review_required": bool(findings),
        "publication_allowed": False,
    }
