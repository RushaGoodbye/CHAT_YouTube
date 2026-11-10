"""Universal SEO v3: source-typed claim ledger BEFORE any SEO writing.

Separate preview-only pipeline. Never calls YouTube, never publishes, and
never silently upgrades a spoken opinion to an independently proven fact.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .seo_v2_pipeline import (
    _ask, _extract, _proof_index, _select_topics, _source_numbers,
    _draft_numbers, validate_draft,
)
from .seo_v2_evidence import parse_srt
from .seo_v2_semantic import independent_review, unsupported_names
from .seo_v3_claims import build_claim_ledger, check_claim_type_constraints

Chat = Callable[[str], dict[str, Any]]


def _write_from_claims(
    ledger: dict[str, Any],
    topics: list[dict[str, Any]],
    chat: Chat,
) -> dict[str, Any]:
    claims = ledger["claims"]
    permitted_ids = {entry["claim_id"] for entry in claims}
    instruction = (
        "You write Ukrainian YouTube SEO from a SOURCE-TYPED CLAIM LEDGER, "
        "not directly from raw subtitles or an earlier AI-generated story. "
        "The source type is mandatory: QUESTION describes a question, "
        "CONDITIONAL describes an if/then possibility, HYPOTHESIS is a "
        "speaker's suggestion, SPEAKER_STATEMENT describes only what "
        "the person said, NOT external verified fact. "
        "NO ledger entry has external verification. NEVER claim that "
        "investigation proved the truth, that a real cause is known, "
        "or that a hypothetical outcome happened. "
        "Do not guess any proper name that is unclear in the original "
        "transcription. Prefer a neutral role or topic over a garbled name. "
        "One primary Ukrainian title and 3 DISTINCT A/B questions or "
        "supported angles; title max 100 chars. "
        "Description: 400-900 chars of attributable factual reporting "
        "about what participants DISCUSS (not about unproven outcomes). "
        "8-15 useful topical tags ONLY when explicitly grounded by "
        "the quote. If the material cannot support 8 tags or 400 chars, "
        "return fewer/shorter; the draft will be blocked for review. "
        "Return JSON ONLY with: title (string), "
        "variant_evidence (exactly 3 objects {text, evidence_ids}), "
        "description (string), tag_evidence (list of objects "
        "{tag, evidence_ids}), support_ids ({title: list of IDs, "
        "description: list of IDs}). Source ID must be from claim_id "
        "and never invented. Citation links must be semantically correct, "
        "not arbitrary. The language of metadata is Ukrainian. "
        "Topic labels are orientation only, NOT sources of facts.\n"
        "TOPIC ORDER:\n"
        + json.dumps(topics, ensure_ascii=False)
        + "\nSOURCE-TYPED CLAIM LEDGER:\n"
        + json.dumps(claims, ensure_ascii=False)
    )
    reply = _ask(chat, instruction)
    support = reply.get("support_ids")
    if not isinstance(support, dict):
        support = {}
    for key, text_key in (("title_variants", "text"), ("tags", "tag")):
        key_in = "variant_evidence" if key == "title_variants" else "tag_evidence"
        raw = reply.get(key_in)
        if not isinstance(raw, list):
            # Legacy output is not trusted: invalid citations are detected
            # by validation rather than fabricated as a convenient fallback.
            continue
        if key == "title_variants":
            raw = raw[:3]
        else:
            raw = raw[:15]
        rows = [
            row for row in raw
            if isinstance(row, dict) and str(row.get(text_key) or "").strip()
        ]
        reply[key] = [str(row[text_key]).strip() for row in rows]
        support[key] = [
            [str(eid) for eid in row.get("evidence_ids") or []
             if isinstance(eid, str) and eid in permitted_ids]
            for row in rows
        ]
    reply["support_ids"] = support
    return reply


def generate_claim_first_seo(
    srt: str,
    chat: Chat,
    independent_review_model: Chat | None = None,
) -> dict[str, Any]:
    """Preview: classify quotes, then draft and independently validate.

    No retries that reintroduce model-generated fictional connections.
    Every rejection stays in the report; publication is never allowed.
    """
    cues = parse_srt(srt)
    evidence, windows = _extract(cues, chat)
    topics = _select_topics(evidence, chat)
    proof = _proof_index(evidence, topics)
    claim_ledger = build_claim_ledger(proof)
    if not claim_ledger["claims"]:
        return {
            "pipeline": "RG_SEO_CLAIM_FIRST_V3",
            "status": "INSUFFICIENT_VERIFIED_EVIDENCE",
            "draft": None,
            "evidence": evidence,
            "claims": claim_ledger,
            "windows": windows,
            "topics": topics,
            "publication_allowed": False,
            "editorial_approved": False,
        }
    visible = {row["claim_id"] for row in claim_ledger["claims"]}
    visible_topics = [
        {**topic, "evidence_ids": [
            i for i in topic["evidence_ids"] if i in visible
        ]}
        for topic in topics
    ]
    draft = _write_from_claims(claim_ledger, visible_topics, chat)
    gate = validate_draft(draft, evidence, cues, allowed_ids=visible)
    modality_issues = check_claim_type_constraints(draft, claim_ledger)
    if modality_issues:
        gate["issues"] = sorted(set([
            *gate["issues"], "CLAIM_MODALITY_UNSUPPORTED",
        ]))
    names = unsupported_names(draft, proof)
    if names:
        gate["issues"] = sorted(set([
            *gate["issues"], "UNVERIFIED_NAMED_ENTITIES",
        ]))
        gate["unverified_names"] = names
    # External information cannot be invented from a question. Treat all
    # spoken statements as attributed statements, never proven journalism.
    extra_numbers = sorted(_draft_numbers(draft) - _source_numbers(cues))
    review = None
    if independent_review_model is not None:
        try:
            review = independent_review(
                draft, proof, independent_review_model,
            )
        except (ValueError, RuntimeError, TypeError, TimeoutError):
            review = {
                "review_status": "FAILED_CLOSED",
                "issues": [{
                    "field": "reviewer",
                    "reason": "INDEPENDENT_REVIEW_UNAVAILABLE",
                }],
            }
    status = "READY_FOR_HUMAN_REVIEW"
    if (gate["issues"] or modality_issues or names or extra_numbers
            or review is None or review.get("issues")):
        status = "REVIEW_REQUIRED"
    return {
        "pipeline": "RG_SEO_CLAIM_FIRST_V3",
        "status": status,
        "draft": {
            key: draft.get(key)
            for key in ("title", "title_variants", "description", "tags",
                        "support_ids")
        },
        "gate": gate,
        "claims": claim_ledger,
        "modality_issues": modality_issues,
        "unverified_names": names,
        "independent_review": review,
        "topics": topics,
        "evidence": evidence,
        "windows": windows,
        "writer_evidence_quotes": len(proof),
        "full_evidence_quotes": len(evidence["accepted"]),
        "publication_allowed": False,
        "editorial_approved": False,
    }
