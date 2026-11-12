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


def _preserves_modality(sentence: str, kind: str) -> bool:
    """Minimal deterministic source-type contract for Ukrainian sentences.

    It does not establish factual truth. An unsupported grammatical mode is
    dropped, never rewritten into a fabricated certainty.
    """
    import re
    text = sentence.casefold()
    signals = {
        "QUESTION": r"(?:пита|запит|запитання|питання|обговор|[?])",
        "CONDITIONAL": r"(?:якщо|якби|за умови|умовн|міг би|могло б|було б|не було б)",
        "HYPOTHESIS": r"(?:припуска|вважає|на думку|можливо|ймовірно|версі|міг би)",
        "SPEAKER_STATEMENT": (
            r"(?:співрозмов|учасник|ведуч|мовець|заяв|сказав|"
            r"зазнач|говорить|розповіда|обговор|за словами|вважає)"
        ),
    }
    pattern = signals.get(kind)
    return bool(pattern and re.search(pattern, text))


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
    # A/B titles must keep the lead video's topic, never a side tangent.
    lead_ids = {
        str(i) for i in ((topics[0].get("evidence_ids") or []) if topics else [])
    } & allowed
    if not lead_ids:
        lead_ids = allowed
    # Titles need a small, clear factual scope. Select a bounded set of
    # literal lead-topic claims in original chronology, not all 24 quotes.
    lead_claims = [c for c in claims if c["claim_id"] in lead_ids][:5]
    lead_ids = {c["claim_id"] for c in lead_claims}
    # Tags should reflect the video's main subjects, not random short
    # exchanges. An unrelated quotation may not be cited as the reason
    # for a high-ranking search keyword.
    selected_ids = {
        str(eid) for topic in topics[:2]
        for eid in topic.get("evidence_ids") or []
    } & allowed
    if not selected_ids:
        selected_ids = allowed
    # Description and tags need a wider but still bounded evidence scope.
    selected_claims = [row for row in claims if row["claim_id"] in selected_ids][:12]
    selected_ids = {row["claim_id"] for row in selected_claims}
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
          "Do not use 'справжня причина', 'реальна причина', "
          "'доведено' or 'встановлено' as a factual assertion. "
          "When citing a QUESTION, frame the title as an unanswered "
          "question about the discussion. No implied confirmed answer. "
          "Return JSON: {\"title\":{\"text\":\"...\","
          "\"evidence_ids\":[\"ev_...\"]},"
          "\"variants\":[{\"text\":\"...\","
          "\"evidence_ids\":[\"ev_...\"]}]}. "
          "All headline variants must focus on the LEAD TOPIC, not "
          "unrelated tangents. Cite only claim_ids in LEAD TOPIC EVIDENCE. "
          "No description and no tags.\nLEAD TOPIC:\n"
        + json.dumps(topics[:1], ensure_ascii=False)
        + "\nLEAD TOPIC EVIDENCE:\n"
        + json.dumps(lead_claims, ensure_ascii=False),
    )
    h = headings.get("title") if isinstance(headings.get("title"), dict) else {}
    title = str(h.get("text") or "").strip()
    title_ids = _support(h.get("evidence_ids"), lead_ids)
    variants: list[str] = []
    variant_ids: list[list[str]] = []
    for item in (headings.get("variants") or [])[:3]:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            variants.append(str(item["text"]).strip())
            variant_ids.append(_support(item.get("evidence_ids"), lead_ids))

    description = _ask_json(
        chat,
        common
        + "TASK 2 OF 3: write 7-8 distinct Ukrainian sentences ABOUT THE "
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
          "Aim for 7-8 complete non-redundant sentences of approximately "
          "65-100 characters each, using distinct literal cited details. "
          "If the available claims cannot support 400 chars, fail short "
          "rather than invent an explanation. "
          "Return JSON: {\"sentences\":[{\"text\":\"...\","
          "\"evidence_ids\":[\"ev_...\"],"
          "\"source_type\":\"QUESTION\"}]}. "
          "Stay focused on the primary topic and truly related "
          "exchanges; do not build causal stories across side tangents. "
          "Do not write title variants or tags.\n"
          "ONLY PRIMARY AND RELATED SECONDARY TOPIC CLAIMS:\n"
        + json.dumps(selected_claims, ensure_ascii=False),
    )
    sentences: list[str] = []
    sentence_ids: list[list[str]] = []
    for row in (description.get("sentences") or [])[:8]:
        if not isinstance(row, dict):
            continue
        sentence = str(row.get("text") or "").strip()
        ids = _support(row.get("evidence_ids"), selected_ids)
        kind = str(row.get("source_type") or "")
        if (not sentence or not ids
                or kind not in {by_id[i]["source_type"] for i in ids}
                or not _preserves_modality(sentence, kind)):
            continue
        sentences.append(sentence)
        sentence_ids.append(ids)
    desc = " ".join(sentences).strip()
    # Add distinct, literally sourced discussion points if the initial
    # response is too short. This is not padding: only unused claim IDs
    # and modality-preserving statements may be added.
    previously_used = {eid for group in sentence_ids for eid in group}
    unused = [row for row in selected_claims if row["claim_id"] not in previously_used]
    if len(desc) < 400 and unused and len(sentences) < 9:
        extra_rows: list[dict[str, Any]] = []
        try:
            addendum = _ask_json(
                chat,
                common
                + "TASK 2 CONTINUATION: The existing Ukrainian description "
                  "is shorter than 400 characters. Add up to FIVE "
                  "distinct, specific Ukrainian sentences about topics "
                  "that have not yet been covered. Cite ONLY unused "
                  "claim_ids listed below; never repeat the existing "
                  "sentences and NEVER assert unverified events. "
                  "A QUESTION must be described as a question, a "
                  "CONDITIONAL as a hypothesis, a SPEAKER_STATEMENT as "
                  "attributed speech. Do not add filler. Return JSON "
                  "with key sentences, each row containing text, "
                  "evidence_ids and source_type.\\n"
                  "EXISTING SENTENCES:\\n"
                + json.dumps(sentences, ensure_ascii=False)
                + "\\nUNUSED LITERAL CLAIMS:\\n"
                + json.dumps(unused, ensure_ascii=False),
            )
            if isinstance(addendum.get("sentences"), list):
                extra_rows = addendum["sentences"][:5]
        except (RuntimeError, ValueError, TypeError, TimeoutError):
            extra_rows = []
        unused_ids = {row["claim_id"] for row in unused}
        for row in extra_rows:
            if not isinstance(row, dict):
                continue
            sentence = str(row.get("text") or "").strip()
            ids = _support(row.get("evidence_ids"), unused_ids)
            kind = str(row.get("source_type") or "")
            if (not sentence or not ids
                    or kind not in {by_id[i]["source_type"] for i in ids}
                    or not _preserves_modality(sentence, kind)
                    or sentence.casefold() in {item.casefold() for item in sentences}
                    or len(desc) + len(sentence) + 1 > 900):
                continue
            sentences.append(sentence)
            sentence_ids.append(ids)
            previously_used.update(ids)
            unused_ids.difference_update(ids)
            desc = " ".join(sentences).strip()
            if len(desc) >= 400:
                break
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
          "Return JSON: {\"tags\":[{\"tag\":\"...\","
          "\"evidence_ids\":[\"ev_...\"]}]}. "
          "Prioritize search phrases from the primary ranked topic. "
          "A genuine QUESTION is a discussion subject, not a fact. "
          "Prefer literal nouns, persons with verified spellings, and "
          "specific themes actually DISCUSSED. Forbidden tag styles: "
          "'реальна причина ...', 'справжня причина ...', unverified "
          "punishment, unverified corruption, or the supposed final "
          "fate of a person. Never promise an answer not in the quote. "
          "No title or description.\n"
          "ONLY PRIMARY AND RELATED SECONDARY TOPIC CLAIMS:\n"
        + json.dumps(selected_claims, ensure_ascii=False),
    )
    tags: list[str] = []
    tag_ids: list[list[str]] = []
    used: set[str] = set()
    for row in (tag_reply.get("tags") or [])[:25]:
        if not isinstance(row, dict):
            continue
        value = str(row.get("tag") or "").strip()
        ids = _support(row.get("evidence_ids"), selected_ids)
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


def check_sentence_provenance(
    draft: dict[str, Any], ledger: dict[str, Any],
) -> list[dict[str, str]]:
    """Fail closed when a description no longer matches its sentence citations.

    A list of overall citations is not proof that each description sentence
    is individually sourced. In particular, a repaired description cannot
    silently reuse the provenance of the text it replaced.
    """
    description = str(draft.get("description") or "").strip()
    sentences = draft.get("sentence_provenance")
    claims = {str(row["claim_id"]): row for row in ledger.get("claims", [])}
    if not description or not isinstance(sentences, list) or not sentences:
        return [{"field": "description", "reason": "SENTENCE_PROVENANCE_MISSING"}]
    parts: list[str] = []
    all_ids: list[str] = []
    for row in sentences:
        if not isinstance(row, dict):
            return [{"field": "description", "reason": "SENTENCE_PROVENANCE_INVALID"}]
        text = str(row.get("text") or "").strip()
        ids = row.get("evidence_ids")
        if not text or not isinstance(ids, list) or not ids or any(
            not isinstance(eid, str) or eid not in claims for eid in ids
        ):
            return [{"field": "description", "reason": "SENTENCE_SOURCE_INVALID"}]
        # Check the final sentence, not only the model's original draft.
        # At least one cited source type must be preserved in its wording.
        # A bare assertion cannot be supported by an unanswered question,
        # conditional scenario, or speaker speculation.
        source_types = {str(claims[eid].get("source_type") or "") for eid in ids}
        if not any(_preserves_modality(text, kind) for kind in source_types):
            return [{"field": "description", "reason": "SENTENCE_MODALITY_UNSUPPORTED"}]
        parts.append(text)
        all_ids.extend(ids)
    if " ".join(parts) != description:
        return [{"field": "description", "reason": "SENTENCE_TEXT_OUT_OF_SYNC"}]
    description_ids = (draft.get("support_ids") or {}).get("description")
    if not isinstance(description_ids, list) or set(description_ids) != set(all_ids):
        return [{"field": "description", "reason": "SENTENCE_IDS_OUT_OF_SYNC"}]
    return []
