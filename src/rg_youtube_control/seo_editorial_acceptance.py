"""G2 editorial review, deliberately separate from source-citation verification.

An LLM critic proposes risk flags only. A human reviewer must sign off on
whether the proposed topic/summary faithfully reflects the whole dialogue.
No automatic publication or editorial PASS is possible through this module.
"""
from __future__ import annotations

import json
from typing import Any, Callable

CRITERIA = ("topic_fidelity", "attribution", "unsupported_details",
            "context_omissions", "language")


def build_editorial_review_packet(
    *, video_id: str, source_records: dict[str, Any],
    transcript_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a non-destructive, reproducible review packet."""
    if source_records.get("video_id") != video_id:
        raise ValueError("VIDEO_ID_MISMATCH")
    if not source_records.get("complete_evidence_coverage"):
        raise ValueError("EVIDENCE_COVERAGE_INCOMPLETE")
    items: list[dict[str, Any]] = []
    for number, rec in enumerate(source_records.get("evidence_records") or [], 1):
        start = float(rec["start_s"])
        end = float(rec["end_s"])
        neighborhood = " ".join(
            str(row.get("text") or "").strip() for row in transcript_rows
            if start - 30 <= float(row.get("start") or -1) <= end + 30
        )
        # A long 60-second context may exceed the display budget. The
        # original implementation cut the first 2500 characters and silently
        # discarded the source quotation at the center/end.
        quote = str(rec["verbatim_quote"])
        position = neighborhood.casefold().find(quote.casefold())
        if position >= 0:
            lo = max(0, position - 750)
            hi = min(len(neighborhood), position + len(quote) + 750)
            neighborhood = neighborhood[lo:hi]
        else:
            # Some ASR passages bridge cue boundaries. Preserve the already
            # verified quotation explicitly while retaining local context.
            neighborhood = (quote + " | КОНТЕКСТ: " + neighborhood[:1600])
        items.append({
            "id": number,
            "block_index": rec["block_index"],
            "start_s": start,
            "end_s": end,
            "proposed_topic": rec["topic"],
            "proposed_summary": rec["model_summary_not_fact"],
            "source_quote": rec["verbatim_quote"],
            "source_context": neighborhood[:2500],
            "source_statement_kind": rec["statement_kind"],
            "factual_truth_verified": False,
            "human_scores": {criterion: None for criterion in CRITERIA},
            "human_reviewer": None,
            "human_approved": False,
        })
    return {
        "schema": "RG_G2_EDITORIAL_REVIEW_V1",
        "video_id": video_id,
        "records": items,
        "criteria": list(CRITERIA),
        "human_review_complete": False,
        "editorial_approved": False,
        "publication_allowed": False,
    }


def independent_llm_critique(
    *, packet: dict[str, Any], chat: Callable[..., str], model: str,
    max_records: int = 30, timeout: float = 75.0,
    generator_model: str | None = None,
) -> dict[str, Any]:
    """Return reviewer suggestions only; never set a pass/approval state."""
    if generator_model and generator_model.casefold() == model.casefold():
        raise ValueError("CRITIC_MUST_DIFFER_FROM_GENERATOR")
    findings = []
    for item in packet.get("records", [])[:max_records]:
        request = {
            "source_context": item["source_context"],
            "verbatim_quote": item["source_quote"],
            "proposed_topic": item["proposed_topic"],
            "proposed_summary": item["proposed_summary"],
            "instruction": (
                "Assess only topic accuracy, whether the summary adds specifics "
                "not supported by the context, and missing qualifiers. "
                "Do not fact-check external events from memory. Return JSON with "
                "risk: low|medium|high, issues: list of short strings, "
                "reason: string. If uncertain, mark medium/high."
            ),
        }
        try:
            raw = chat(
                [{"role": "system", "content": "Independent critic, not publication approver. JSON only."},
                 {"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
                model=model, timeout=timeout, temperature=0, json_mode=True,
            )
            candidate = json.loads(str(raw))
            if candidate.get("risk") not in ("low", "medium", "high"):
                raise ValueError("INVALID_CRITIC_RISK")
            issues = candidate.get("issues")
            if not isinstance(issues, list):
                raise ValueError("INVALID_CRITIC_ISSUES")
            findings.append({
                "id": item["id"], "risk": candidate["risk"],
                "issues": [str(x)[:240] for x in issues[:10]],
                "reason": str(candidate.get("reason") or "")[:500],
            })
        except (ValueError, TypeError, KeyError, TimeoutError, RuntimeError, OSError):
            findings.append({"id": item["id"], "risk": "high",
                             "issues": ["CRITIC_UNAVAILABLE"], "reason": ""})
    return {
        "schema": "RG_G2_EDITORIAL_CRITIQUE_V1",
        "video_id": packet.get("video_id"),
        "critic_model": model,
        "checked": len(findings),
        "findings": findings,
        "editorial_approved": False,
        "publication_allowed": False,
    }
