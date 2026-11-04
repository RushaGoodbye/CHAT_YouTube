"""Offline G3 batch SEO drafts grounded in actual G2 source records.

This module NEVER publishes or grants semantic approval. AI-created packages
remain source-linked drafts with independent critic opinions for triage.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from .seo_spoken_numbers import grounded_number_values

Chat = Callable[[list[dict[str, str]]], str]
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _json(response: str) -> dict[str, Any]:
    raw = str(response or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^\x60{3}(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*\x60{3}$", "", raw).strip()
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("MODEL_DID_NOT_RETURN_JSON") from None
    if not isinstance(result, dict):
        raise ValueError("MODEL_JSON_NOT_OBJECT")
    return result


def prepare_source_packet(*, video_id: str, cards: list[dict[str, Any]],
                          max_cards: int = 12) -> dict[str, Any]:
    if not VIDEO_ID_RE.fullmatch(video_id or ""):
        raise ValueError("INVALID_VIDEO_ID")
    if not cards or len(cards) > max_cards:
        raise ValueError("INVALID_SOURCE_CARD_COUNT")
    selected = []
    ids: set[int] = set()
    for card in sorted(cards, key=lambda x: float(x.get("start_s") or 0)):
        if card.get("video_id") != video_id or card.get("publication_allowed") is not False:
            raise ValueError("UNTRUSTED_SOURCE_CARD")
        rid, quote, context = card.get("record_id"), card.get("source_quote"), card.get("source_context")
        topic = card.get("candidate_topic") or card.get("revised_topic") or card.get("initial_topic")
        if (type(rid) is not int or rid in ids or
                not isinstance(quote, str) or len(quote.strip()) < 8 or
                not isinstance(context, str) or quote not in context or
                not isinstance(topic, str) or len(topic.strip()) < 5):
            raise ValueError("SOURCE_QUOTE_INTEGRITY_FAILURE")
        ids.add(rid)
        selected.append({
            "id": rid,
            "start_s": round(float(card.get("start_s") or 0), 2),
            "topic_candidate_not_fact": topic.strip(),
            "literal_quote": quote.strip(),
            "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "source_context": context[:3500],
            "provisional": card.get("status") in {
                "BLOCKED", "VAGUE_TOPIC_NEEDS_REVIEW", "PROVISIONAL_SOURCE_REVIEW"},
        })
    provisional = any(c["provisional"] for c in selected)
    return {
        "video_id": video_id,
        "records": selected,
        "source_packet_sha256": _fingerprint(selected),
        "contains_provisional_sources": provisional,
        "editorial_approved": False,
        "publication_allowed": False,
    }


def draft_seo_package(*, source: dict[str, Any], chat: Chat) -> dict[str, Any]:
    """One call to local LLM, then deterministic checks. No auto-publish."""
    records = source.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("EMPTY_SOURCE_PACKET")
    task = {
        "task": "Create Ukrainian YouTube SEO for ONE actual video. ONLY supplied captions are evidence.",
        "instructions": [
            "Return JSON with title, title_variants (exactly 3), description and tags (8-16 strings).",
            "Main title and each A/B alternative <=100 characters and substantially different.",
            "Description 300-1400 characters, concrete and fluent Ukrainian.",
            "Do not invent dates, casualty numbers, locations, people, quotes, results or certainty.",
            "Attribute controversial claims to speakers; do not turn them into established facts.",
            "Keep video ID out of SEO text and never imply an unverified factual event happened.",
            "No Russian grammar, fabricated hooks or irrelevant generic keywords.",
            "No publishing instructions. This is an unapproved local draft."
        ],
        "source": {"video_id": source["video_id"], "records": [
            {"start_s": r["start_s"],"topic_not_fact": r["topic_candidate_not_fact"],
             "quote": r["literal_quote"],"context": r["source_context"][:900]}
            for r in records
        ]},
    }
    response = chat([
        {"role": "system", "content": "Професійний український SEO-редактор. Лише JSON. Не вигадуй факти."},
        {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
    ])
    package = _json(response)
    try:
        from .seo_quality_gate import inspect_package
    except ImportError:
        raise ValueError("MISSING_EXISTING_QUALITY_GATE") from None
    result = inspect_package(package)
    texts = [str(package.get("title") or ""),
             *[str(v) for v in (package.get("title_variants") or [])],
             str(package.get("description") or ""),
             *[str(t) for t in (package.get("tags") or [])]]
    source_text = " ".join(x["source_context"] for x in records)
    unsupported = sorted(set().union(*(grounded_number_values(s) for s in texts))
                         - grounded_number_values(source_text))
    # A topic/theme is not source truth: this is format+numeric QA only.
    reasons = list(result["problems"].keys())
    if unsupported:
        reasons.append("UNSUPPORTED_NUMBERS")
    if source.get("contains_provisional_sources"):
        reasons.append("PROVISIONAL_SOURCE_REVIEW")
    return {
        "schema": "RG_G3_SEO_DRAFT_V1",
        "video_id": source["video_id"],
        "source_packet_sha256": source["source_packet_sha256"],
        "seo": package,
        "quality_checks": {**result, "unsupported_numbers": unsupported},
        "status": "READY_FOR_INDEPENDENT_AI_REVIEW" if not reasons else "NEEDS_FIX",
        "blockers": reasons,
        "human_approved": False,
        "g3_accepted": False,
        "publication_allowed": False,
    }


def evaluate_independent_draft(
    *, draft: dict[str, Any], source: dict[str, Any], chat: Chat
) -> dict[str, Any]:
    if (draft.get("schema") != "RG_G3_SEO_DRAFT_V1" or
            draft.get("source_packet_sha256") != source.get("source_packet_sha256") or
            draft.get("video_id") != source.get("video_id")):
        raise ValueError("SOURCE_DRAFT_MISMATCH")
    # Independent model must see ORIGINAL source, not previous model's
    # unsupported rationalization or self-reported risk.
    prompt = {
        "task": "Critically check factual entailment of ALL SEO claims against ORIGINAL provided captions.",
        "response": "JSON object with risk (low, medium, high) and issues (array of short strings).",
        "rules": [
            "Flag unsupported dates, locations, names, numbers and quotes.",
            "Flag confident attribution of unverified claims as facts.",
            "Flag keyword-stuffed or awkward Ukrainian.",
            "Compare full description and every title to each exact source quote.",
            "A low risk opinion is NOT human approval or factual verification."
        ],
        "source": source["records"],
        "seo_candidate": draft["seo"],
    }
    result = _json(chat([
        {"role": "system", "content": "Independent adversarial Ukrainian editorial critic. Only JSON."},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]))
    risk = result.get("risk")
    issues = result.get("issues")
    if risk not in {"low", "medium", "high"} or not isinstance(issues, list) or any(
            not isinstance(i, str) for i in issues):
        raise ValueError("INVALID_INDEPENDENT_CRITIQUE")
    requires_manual = (
        risk != "low" or draft["status"] != "READY_FOR_INDEPENDENT_AI_REVIEW")
    return {
        "schema": "RG_G3_INDEPENDENT_REVIEW_V1",
        "video_id": source["video_id"],
        "source_packet_sha256": source["source_packet_sha256"],
        "risk_ai": risk,
        "issues": issues[:15],
        "status": "NEEDS_ATTENTION" if requires_manual else "AI_SCREENED_DRAFT",
        "editorial_review_required": True,
        "human_approved": False,
        "g3_accepted": False,
        "publication_allowed": False,
    }
