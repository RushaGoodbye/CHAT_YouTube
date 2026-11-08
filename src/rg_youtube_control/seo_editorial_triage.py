"""G2 editorial risk triage: preserve critic objections and source context.

A model's risk label is not ground truth. A human must decide whether the
complaint is correct, then accept, revise or reject the proposed topic.
"""
from __future__ import annotations

from typing import Any


def vague_topic_warning(topic: str) -> bool:
    """Warn on low-information topics; only human review determines meaning.

    This is a conservative editorial warning, not an automatic rejection.
    Avoids publishing nonspecific phrases without silently excluding clips.
    """
    import re

    tokens = set(re.findall(r"[^\W_]+", str(topic or "").casefold()))
    placeholders = {
        "щось", "дещо", "якийсь", "якась", "якісь", "невідоме",
        "неизвестное", "что-то", "кое-что", "something",
    }
    return (bool(tokens & placeholders)
            or any(hyphenated in str(topic or "").casefold()
                   for hyphenated in ("что-то", "кое-что"))
            or len(tokens) < 2)


def triage_editorial_reviews(
    *, packet: dict[str, Any], critique: dict[str, Any],
) -> dict[str, Any]:
    if packet.get("video_id") != critique.get("video_id"):
        raise ValueError("REVIEW_SOURCE_MISMATCH")
    records = {item.get("id"): item for item in packet.get("records") or []}
    findings = critique.get("findings") or []
    if not records:
        raise ValueError("EMPTY_EDITORIAL_PACKET")
    if len(findings) != len(records) or len({f.get("id") for f in findings}) != len(findings):
        raise ValueError("INCOMPLETE_CRITIC_COVERAGE")
    queue = []
    for finding in findings:
        rid = finding.get("id")
        if rid not in records or finding.get("risk") not in ("low", "medium", "high"):
            raise ValueError("INVALID_CRITIC_FINDING")
        item = records[rid]
        risk = finding["risk"]
        queue.append({
            "id": rid,
            "video_id": packet["video_id"],
            "block_index": item["block_index"],
            "start_s": item["start_s"],
            "risk_label_ai_only": risk,
            "proposed_topic": item["proposed_topic"],
            "proposed_summary": item["proposed_summary"],
            "verbatim_quote": item["source_quote"],
            "source_context": item["source_context"],
            "critic_issues_unverified": finding.get("issues") or [],
            "critic_reason_unverified": finding.get("reason") or "",
            "vague_topic_warning": vague_topic_warning(item["proposed_topic"]),
            "reviewer_decision": None,
            "reviewer_notes": "",
            "requires_human_review": True,
            "editorial_approved": False,
        })
    priority = {"high": 0, "medium": 1, "low": 2}
    queue.sort(key=lambda item: (priority[item["risk_label_ai_only"]], item["id"]))
    return {
        "schema": "RG_G2_EDITORIAL_TRIAGE_V1",
        "video_id": packet["video_id"],
        "total": len(queue),
        "priority_count": sum(x["risk_label_ai_only"] != "low" for x in queue),
        "queue": queue,
        "reviewer_decision_values": ["accept", "revise", "reject"],
        "editorial_approved": False,
        "publication_allowed": False,
    }
