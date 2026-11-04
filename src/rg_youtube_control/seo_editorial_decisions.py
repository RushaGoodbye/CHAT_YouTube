"""Read-only G2 editorial decisions contract.

An editor's explicit decisions are distinct from AI risk labels. Never
auto-approve, infer a decision from a missing record, or publish from import.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

DECISIONS_SCHEMA = "RG_G2_HUMAN_DECISIONS_V1"
_DECISIONS = {"approve", "revise", "reject"}


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def create_review_manifest(packet: dict[str, Any]) -> dict[str, Any]:
    records = packet.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("MISSING_REVIEW_RECORDS")
    unique: set[tuple[str, int]] = set()
    fingerprints = []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("INVALID_REVIEW_RECORD")
        video_id = item.get("video_id")
        record_id = item.get("record_id")
        quote = item.get("source_quote")
        if (not isinstance(video_id, str) or
                not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or
                type(record_id) is not int or record_id < 1 or
                not isinstance(quote, str) or len(quote.strip()) < 8):
            raise ValueError("INVALID_REVIEW_RECORD")
        key = (video_id, record_id)
        if key in unique:
            raise ValueError("DUPLICATE_REVIEW_RECORD")
        unique.add(key)
        fingerprints.append({
            "video_id": video_id,
            "record_id": record_id,
            "source_quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "candidate_sha256": _sha({
                "topic": item.get("revised_topic") or item.get("initial_topic") or "",
                "summary": item.get("revised_summary") or item.get("initial_summary") or "",
                "status": item.get("status"),
            }),
        })
    return {
        "schema": "RG_G2_REVIEW_MANIFEST_V1",
        "manifest_sha256": _sha(fingerprints),
        "cards": fingerprints,
        "holdout_evaluated": 0,
        "publication_allowed": False,
    }


def validate_editorial_decisions(
    *, packet: dict[str, Any], submission: dict[str, Any],
) -> dict[str, Any]:
    """Validate human-entered, source-bound decisions without granting release.

    Partial review is supported. Unreviewed records remain pending. A blocked
    proposal may be rejected or explicitly revised, but cannot be approved.
    """
    manifest = create_review_manifest(packet)
    if not isinstance(submission, dict) or submission.get("schema") != DECISIONS_SCHEMA:
        raise ValueError("INVALID_DECISION_SCHEMA")
    if submission.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("SOURCE_MANIFEST_MISMATCH")
    reviewer = submission.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("MISSING_REVIEWER")
    provided = submission.get("decisions")
    if not isinstance(provided, list):
        raise ValueError("INVALID_DECISIONS")
    allowed = {(x["video_id"], x["record_id"]): x for x in manifest["cards"]}
    cards = {(x["video_id"], x["record_id"]): x for x in packet["records"]}
    seen = set()
    validated = []
    for d in provided:
        if not isinstance(d, dict):
            raise ValueError("INVALID_DECISION")
        key = (d.get("video_id"), d.get("record_id"))
        if key in seen or key not in allowed:
            raise ValueError("DUPLICATE_OR_UNKNOWN_DECISION")
        seen.add(key)
        original = allowed[key]
        if (d.get("source_quote_sha256") != original["source_quote_sha256"] or
                d.get("candidate_sha256") != original["candidate_sha256"]):
            raise ValueError("DECISION_SOURCE_CHANGED")
        decision = d.get("decision")
        if decision not in _DECISIONS:
            raise ValueError("INVALID_DECISION")
        note = str(d.get("note") or "").strip()
        topic = str(d.get("corrected_topic") or "").strip()
        summary = str(d.get("corrected_summary") or "").strip()
        if decision == "approve" and cards[key].get("status") in {
            "BLOCKED", "VAGUE_TOPIC_NEEDS_REVIEW",
        }:
            raise ValueError("FLAGGED_CARD_REQUIRES_REVISION_OR_REJECTION")
        if decision == "approve" and (topic or summary):
            raise ValueError("APPROVAL_CANNOT_SILENTLY_REWRITE")
        if decision == "revise" and (not (5 <= len(topic) <= 110) or
                                      not (15 <= len(summary) <= 350) or not note):
            raise ValueError("INCOMPLETE_REVISION")
        if decision == "reject" and not note:
            raise ValueError("REJECTION_REQUIRES_REASON")
        validated.append({
            "video_id": key[0], "record_id": key[1],
            "decision": decision, "corrected_topic": topic if decision == "revise" else "",
            "corrected_summary": summary if decision == "revise" else "",
            "note": note,
            "reviewer_attested": reviewer.strip(),
            "editorial_approved": decision == "approve",
            "publication_allowed": False,
        })
    return {
        "schema": "RG_G2_HUMAN_REVIEW_VALIDATED_V1",
        "manifest_sha256": manifest["manifest_sha256"],
        "total_cards": len(cards),
        "reviewed": len(validated),
        "pending": len(cards) - len(validated),
        "decisions": validated,
        "g2_accepted": False,
        "publication_allowed": False,
    }
