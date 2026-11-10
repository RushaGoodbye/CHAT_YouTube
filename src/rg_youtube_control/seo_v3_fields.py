"""SEO v3 field composers: three bounded source-grounded writing tasks.

No all-in-one story-writing prompt. Description is assembled from individual
claim-attributed sentences, each tied to an immutable source quote.
"""
from __future__ import annotations

import json
from typing import Any, Callable

Chat = Callable[[str], dict[str, Any]]


def _ask_json(chat: Chat, prompt: str) -> dict[str, Any]:
    value = chat(prompt)
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("Source-grounded field composer requires JSON object")
    return value


def _support(rows: Any, allowed: set[str]) -> list[str]:
    if not isinstance(rows, list):
        return []
    return list(dict.fromkeys(
        str(item) for item in rows
        if isinstance(item, str) and item in allowed
    ))


def compose_claim_fields(
    ledger: dict[str, Any],
    topics: list[dict[str, Any]],
    chat: Chat,
) -> dict[str, Any]:
    """Create only evidence-linked fields. Never pad invalid or missing data."""
    claims = ledger["claims"]
    by_id = {row["claim_id"]: row for row in claims}
    allowed = set(by_id)
    data = json.dumps(claims, ensure_ascii=False)
    topic_hint = json.dumps(topics, ensure_ascii=False)
    common = (
        "Only use the SOURCE-TYPED CLAIM LEDGER. Every source entry records "
        "what was SPOKEN, never independently verified truth. QUESTION = "
        "unanswered question, CONDITIONAL = hypothetical, HYPOTHESIS = "
        "subjective possibility, SPEAKER_STATEMENT = words of a speaker. "
        "Never turn any of these into a proven outcome, true motive, "
        "causal deduction or objective investigation. "
        "Never guess a distorted proper name. Work in fluent Ukrainian. "
        "Use exact claim_id values as evidence IDs. "
        "Return ONLY valid JSON. "
    )
    headings = _ask_json(
        chat,
        common
        + "TASK 1 OF 3: write one specific, compelling Ukrainian YouTube "
          "headline (max 100 chars) and THREE genuinely different A/B "
          "headlines (max 100 chars each). Use QUESTIONS for uncertain "
          "causes and outcomes; describe the dispute rather than asserting "
          "'real reasons', findings or punishments. "
          "Return JSON: {\\\"title\\\":{\\\"text\\\":\\\"...\\\","
          "\\\"evidence_ids\\\":[\\\"ev_...\\\"]},"
          "\\\"variants\\\":[{\\\"text\\\":\\\"...\\\","
          "\\\"evidence_ids\\\":[\\\"ev_...\\\"]}]}. "
          "No description and no tags.\\nTOPICS (not facts):\\n"
        + topic_hint + "\\nSOURCE-TYPED CLAIMS:\\n" + data,
    )
    h = headings.get("title") if isinstance(headings.get("title"), dict) else {}
    title = str(h.get("text") or "").strip()
    title_ids = _support(h.get("evidence_ids"), allowed)
    variants: list[str] = []
    variant_ids: list[list[str]] = []
    for item in (headings.get("variants") or [])[:3]:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            variants.append(str(item["text"]).strip())
            variant_ids.append(_support(item.get("evidence_ids"), allowed))

    description = _ask_json(
        chat,
        common
        + "TASK 2 OF 3: write 5-7 concise Ukrainian sentences ABOUT THE "
          "DISCUSSION, not a narrative of supposedly proven events. "
          "Each sentence must focus on ONE cited claim and preserve its "
          "source_type: for QUESTION say what was asked, CONDITIONAL "
          "must retain if/then, HYPOTHESIS must be attributed as a "
          "suggestion, SPEAKER_STATEMENT as something a person said. "
          "Do NOT use wording such as 'аналіз довів', 'справжня причина "
          "встановлена' or confirmed outcome unless externally verified "
          "(no source here is). Target 400-900 characters IN TOTAL, only "
          "when enough source material supports them; do not repeat "
          "sentences merely to reach the target. "
          "Return JSON: {\\\"sentences\\\":[{\\\"text\\\":\\\"...\\\","
          "\\\"evidence_ids\\\":[\\\"ev_...\\\"],"
          "\\\"source_type\\\":\\\"QUESTION\\\"}]}. "
          "Do not write title variants or tags.\\n"
          "SOURCE-TYPED CLAIMS:\\n" + data,
    )
    sentences: list[str] = []
    sentence_ids: list[list[str]] = []
    for row in (description.get("sentences") or [])[:8]:
        if not isinstance(row, dict):
            continue
        sentence = str(row.get("text") or "").strip()
        ids = _support(row.get("evidence_ids"), allowed)
        kind = str(row.get("source_type") or "")
        if (not sentence or not ids
                or kind not in {by_id[i]["source_type"] for i in ids}):
            continue
        sentences.append(sentence)
        sentence_ids.append(ids)
    desc = " ".join(sentences).strip()
    desc_ids = list(dict.fromkeys(
        i for group in sentence_ids for i in group
    ))

    tag_reply = _ask_json(
        chat,
        common
        + "TASK 3 OF 3: generate 8-15 DISTINCT and natural Ukrainian "
          "YouTube search phrases that describe DISCUSSED SUBJECTS, "
          "not outcomes, invented facts, unsupported persons or claims "
          "that speculative events happened. Diversify phrases across "
          "different cited topics. Every tag must cite actual source IDs. "
          "If fewer than 8 specific source-supported phrases exist, "
          "return fewer and let quality control block the draft. "
          "Return JSON: {\\\"tags\\\":[{\\\"tag\\\":\\\"...\\\","
          "\\\"evidence_ids\\\":[\\\"ev_...\\\"]}]}. "
          "No title or description.\\n"
          "SOURCE-TYPED CLAIMS:\\n" + data,
    )
    tags: list[str] = []
    tag_ids: list[list[str]] = []
    used: set[str] = set()
    for row in (tag_reply.get("tags") or [])[:25]:
        if not isinstance(row, dict):
            continue
        value = str(row.get("tag") or "").strip()
        ids = _support(row.get("evidence_ids"), allowed)
        if not value or not ids or value.casefold() in used:
            continue
        tags.append(value)
        tag_ids.append(ids)
        used.add(value.casefold())
        if len(tags) == 15:
            break
    return {
        "title": title,
        "title_variants": variants,
        "description": desc,
        "tags": tags,
        "support_ids": {
            "title": title_ids,
            "title_variants": variant_ids,
            "description": desc_ids,
            "tags": tag_ids,
        },
        "sentence_provenance": [
            {"text": sentence, "evidence_ids": ids}
            for sentence, ids in zip(sentences, sentence_ids)
        ],
    }
