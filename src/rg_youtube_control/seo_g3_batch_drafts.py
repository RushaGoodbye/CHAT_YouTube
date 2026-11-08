"""Offline G3 batch SEO drafts grounded in actual G2 source records.

This module NEVER publishes or grants semantic approval. AI-created packages
remain source-linked drafts with independent critic opinions for triage.
"""
from __future__ import annotations

import hashlib
import json
import math
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
                          max_cards: int = 12,
                          expanded_evidence: dict[str, Any] | None = None,
                          transcript_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
    # Optional exact SRT cue supplements. Existing approved source cards take
    # precedence. New cues remain provisional, even when their literal origin
    # is verified: a quote does not establish meaning, speaker or factual truth.
    if expanded_evidence is not None:
        # A literal-only transcript proof is eligible for a REVIEW-ONLY draft
        # even when the model misquotes a topic or a timeline block is
        # semantically unverified. It is NEVER an editorial approval.
        literal_only = expanded_evidence.get("complete_evidence_coverage") is not True
        if (expanded_evidence.get("video_id") != video_id
                or expanded_evidence.get("source_cue_selection_schema") != "RG_SOURCE_CUE_EXPANSION_V1"
                or expanded_evidence.get("source_cue_candidates_review_only") is not True
                or expanded_evidence.get("complete_literal_source_coverage") is not True
                or expanded_evidence.get("source_cue_invalid_block_count") != 0
                or not isinstance(expanded_evidence.get("source_cue_candidates"), list)):
            raise ValueError("UNTRUSTED_EXPANDED_SOURCE_EVIDENCE")
        # Re-check every candidate against ORIGINAL timestamped captions.
        # A self-reported "source verified" field cannot establish provenance.
        if not isinstance(transcript_rows, list) or not transcript_rows:
            raise ValueError("ORIGINAL_SRT_REQUIRED_FOR_EXPANDED_EVIDENCE")
        actual_rows = set()
        for row in transcript_rows:
            if not isinstance(row, dict):
                continue
            try:
                stamp = float(row["start"])
            except (KeyError, ValueError, TypeError):
                continue
            if not (math.isfinite(stamp) and stamp >= 0):
                continue
            actual_rows.add((round(stamp, 3), " ".join(str(row.get("text") or "").split())))
        expected = []
        for cue in expanded_evidence.get("source_cue_candidates") or []:
            if not isinstance(cue, dict):
                raise ValueError("INVALID_EXPANDED_CUE")
            try:
                candidate_start = float(cue["start_s"])
            except (KeyError, ValueError, TypeError):
                raise ValueError("INVALID_EXPANDED_CUE_TIME") from None
            candidate_quote = " ".join(str(cue.get("source_quote") or "").split())
            if (not math.isfinite(candidate_start)
                    or (round(candidate_start, 3), candidate_quote) not in actual_rows):
                raise ValueError("EXPANDED_CUE_NOT_IN_ORIGINAL_SRT")
            expected.append(candidate_quote)
        known_quotes = {r["literal_quote"].casefold() for r in selected}
        next_id = max(ids, default=0) + 1
        # Preserve both the beginning and end of long transcripts. Truncating
        # the first N chronologically sorted cues silently drops later topics.
        remaining = max_cards - len(selected)
        all_cues = sorted(
            expanded_evidence.get("source_cue_candidates") or [],
            key=lambda x: float(x.get("start_s") or 0)
        )
        all_cues = [
            cue for cue in all_cues
            if isinstance(cue, dict)
            and str(cue.get("source_quote") or "").strip().casefold() not in known_quotes
        ]
        if remaining > 0 and len(all_cues) > remaining:
            if remaining == 1:
                all_cues = [all_cues[len(all_cues) // 2]]
            else:
                indexes = [
                    round(i * (len(all_cues) - 1) / (remaining - 1))
                    for i in range(remaining)
                ]
                all_cues = [all_cues[index] for index in indexes]
        for cue in all_cues:
            if len(selected) >= max_cards:
                break
            if not isinstance(cue, dict):
                continue
            quote = str(cue.get("source_quote") or "").strip()
            if (not 28 <= len(quote) <= 220
                    or quote.casefold() in known_quotes
                    or cue.get("source_precision") != "single_original_cue"
                    or cue.get("factual_truth_verified") is not False
                    or not isinstance(cue.get("start_s"), (int, float))):
                continue
            known_quotes.add(quote.casefold())
            # Context may include adjacent speakers; it is not attribution.
            cue_context = str(cue.get("context_window") or "").strip()
            if quote not in cue_context or len(cue_context) > 700:
                cue_context = quote
            selected.append({
                "id": next_id,
                "start_s": round(float(cue["start_s"]), 2),
                "topic_candidate_not_fact": "Дослівна репліка з SRT: зміст потребує перевірки",
                "literal_quote": quote,
                "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                "source_context": cue_context,
                "context_is_not_speaker_proof": True,
                "model_block_verified": cue.get("model_block_verified") is True,
                "provisional": True,
                "incomplete_source_fragment": bool(cue.get("may_be_incomplete")),
            })
            next_id += 1
        selected.sort(key=lambda item: (item["start_s"], item["id"]))
    provisional = any(c["provisional"] for c in selected) or expanded_evidence is not None
    return {
        "video_id": video_id,
        "expanded_literal_only": bool(expanded_evidence is not None and literal_only),
        "source_material_requires_editorial_review": expanded_evidence is not None,
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
            "Return one JSON object with EXACTLY four keys: title, title_variants, description, tags.",
            "title_variants MUST be an array of EXACTLY THREE nonempty Ukrainian strings: [variant_1, variant_2, variant_3]. Two variants are an invalid response.",
            "Title and each A/B variant must be <=100 characters; three different, source-supported angles. Never pad with unsupported invented hooks.",
            "Description 300-1400 characters, concrete and fluent Ukrainian.",
            "Do not invent dates, casualty numbers, locations, people, quotes, results or certainty.",
            "Treat source lines as fragments of a dialogue, not a news report. Do not claim that a reported statement represents an official policy or verified event.",
            "Do not add 'several sources', motives, consequences or other surrounding topics without literal source support.",
            "Attribute disputed positions to an unidentified participant, not to a named speaker, unless speaker identity is independently established.",
            "Source coverage matters: select distinct substantive topics from early and late captions rather than elaborating one quote into the whole description.",
            "Keep video ID out of SEO text and never imply an unverified factual event happened.",
            "No Russian grammar, fabricated hooks or irrelevant generic keywords.",
            "A subtitle cue, especially a fragment, may be incomplete or spoken by another person.",
            "Never infer speaker identity or link adjacent source cues as one person's statement.",
            "No publishing instructions. This is an unapproved local draft."
        ],
        "source": {"video_id": source["video_id"], "records": [
            {"start_s": r["start_s"],"topic_not_fact": r["topic_candidate_not_fact"],
             "quote": r["literal_quote"],"context": r["source_context"][:900],
             "provisional": bool(r.get("provisional")),
             "may_be_incomplete": bool(r.get("incomplete_source_fragment")),
             "speaker_unknown": bool(r.get("context_is_not_speaker_proof")),
             "model_block_verified": r.get("model_block_verified") is True
                 if r.get("context_is_not_speaker_proof") else None}
            for r in records
        ]},
    }
    messages = [
        {"role": "system", "content": "Професійний український SEO-редактор. Лише JSON. Не вигадуй факти."},
        {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
    ]
    response = chat(messages)
    if not str(response or "").strip():
        response = chat(messages + [{"role": "user", "content": "Відповідь була порожня. Поверни лише повний JSON за вихідним завданням."}])
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
    if any(r["literal_quote"] not in r["source_context"] for r in source["records"]):
        raise ValueError("CRITIC_SOURCE_QUOTE_MISMATCH")
    compact_source = []
    for r in source["records"]:
        quote = r["literal_quote"]
        context = r["source_context"]
        start = max(0, context.find(quote) - 320)
        end = context.find(quote) + len(quote) + 320
        compact_source.append({
            "start_s": r["start_s"],
            "literal_quote": quote,
            "source_context": context[start:end],
            "topic_candidate_not_fact": r["topic_candidate_not_fact"],
        })
    prompt = {
        "task": "Critically check factual entailment of ALL SEO claims against ORIGINAL provided captions.",
        "response": "JSON object with risk (low, medium, high) and issues (array of short strings).",
        "rules": [
            "Flag unsupported dates, locations, names, numbers and quotes.",
            "Flag confident attribution of unverified claims as facts.",
            "Flag keyword-stuffed or awkward Ukrainian.",
            "Reject question-to-assertion swaps, false participant identities, inferred state policies or definitive external facts from quoted dialogue.",
            "Reject invented causal links, 'other sources', dates, consequences and topic drift not supported by exact caption context.",
            "Compare main title, ALL THREE A/B titles, every substantive description claim and tags to exact source quotes. Report absent A/B variants.",
            "A low risk opinion is NOT human approval or factual verification."
        ],
        "source": compact_source,
        "seo_candidate": draft["seo"],
    }
    result = _json(chat([
        {"role": "system", "content": "Independent adversarial Ukrainian editorial critic. Only JSON."},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]))
    risk = result.get("risk")
    issues = result.get("issues")
    # Some local critics emit a single issue as a JSON string rather than
    # a one-item array. Preserve the veto; do not silently discard findings.
    if isinstance(issues, str):
        issues = [issues] if issues.strip() else []
    if risk not in {"low", "medium", "high"} or not isinstance(issues, list) or any(
            not isinstance(i, str) for i in issues):
        raise ValueError("INVALID_INDEPENDENT_CRITIQUE")
    requires_manual = (
        risk != "low" or bool(issues) or
        draft["status"] != "READY_FOR_INDEPENDENT_AI_REVIEW" or
        source.get("contains_provisional_sources", True))
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


def repair_seo_package(
    *, source: dict[str, Any], previous: dict[str, Any],
    critique: dict[str, Any], chat: Chat,
) -> dict[str, Any]:
    """One bounded source-aware rewrite. Recheck structure and numbers as new.

    Never count a rewrite as independent AI review. That requires a different
    model afterward and a separate explicit human decision for publication.
    """
    if (previous.get("schema") != "RG_G3_SEO_DRAFT_V1" or
            previous.get("source_packet_sha256") != source.get("source_packet_sha256")
            or previous.get("video_id") != source.get("video_id")):
        raise ValueError("SOURCE_DRAFT_MISMATCH")
    if (critique.get("schema") != "RG_G3_INDEPENDENT_REVIEW_V1" or
            critique.get("source_packet_sha256") != source.get("source_packet_sha256")
            or critique.get("video_id") != source.get("video_id")):
        raise ValueError("SOURCE_CRITIQUE_MISMATCH")
    if (previous.get("status") == "READY_FOR_INDEPENDENT_AI_REVIEW"
            and critique.get("risk_ai") == "low"
            and not critique.get("issues")
            and not source.get("contains_provisional_sources")):
        raise ValueError("ALREADY_AI_SCREENED_DO_NOT_REWRITE")
    issues = {
        "structure": previous.get("quality_checks", {}).get("problems", {}),
        "unsupported_numbers": previous.get("quality_checks", {}).get("unsupported_numbers", []),
        "critic_issues": critique.get("issues", []),
    }
    def rewrite(_original_messages: list[dict[str, str]]) -> str:
        return chat([
            {"role": "system", "content": "Редагуй українське SEO за джерелом. Поверни лише JSON."},
            {"role": "user", "content": json.dumps({
                "task": "Rewrite one flawed YouTube SEO package with minimal changes to truthful source-grounded content.",
                "required": {
                    "title": "string <= 100 characters",
                    "title_variants": "array of EXACTLY three DISTINCT strings, each <=100 characters",
                    "description": "single coherent Ukrainian text 300-1400 characters",
                    "tags": "array 8-16 concrete Ukrainian keywords",
                },
                "source_records_not_external_facts": source["records"],
                "previous_draft": previous["seo"],
                "defects_to_fix": issues,
                "rules": [
                    "No unsupported numeric values, names, dates or locations.",
                    "No invented claims, filler or keyword repetition.",
                    "Reflect direct speaker claims as opinions, not facts.",
                    "Do not alter video ID or source quotes.",
                    "Keep 3 genuinely distinct Ukrainian A/B angles.",
                ],
            }, ensure_ascii=False)},
        ])
    revised = draft_seo_package(source=source, chat=rewrite)
    revised["repair_attempt"] = 1
    revised["previous_draft_sha256"] = _fingerprint(previous.get("seo"))
    revised["previous_critic_risk"] = critique.get("risk_ai")
    revised["independent_recheck_required"] = True
    return revised


def complete_missing_source_variants(
    *, source: dict[str, Any], draft: dict[str, Any],
) -> dict[str, Any]:
    """Complete absent A/B alternatives only using original G2 source topics.

    Preserve all other SEO fields verbatim. No fabricated filler headlines,
    and never convert a repaired package into final editorial approval.
    """
    from .seo_quality_gate import inspect_package, sanitize_review_variants

    if (draft.get("schema") != "RG_G3_SEO_DRAFT_V1" or
            draft.get("source_packet_sha256") != source.get("source_packet_sha256") or
            draft.get("video_id") != source.get("video_id")):
        raise ValueError("SOURCE_DRAFT_MISMATCH")
    package = draft.get("seo")
    if not isinstance(package, dict):
        raise ValueError("INVALID_SEO_PACKAGE")
    existing = package.get("title_variants")
    if (not isinstance(existing, list) or len(existing) != 2 or
            not all(isinstance(item, str) for item in existing) or
            any(k != "title_variants" for k in draft.get("quality_checks", {}).get("problems", {}))):
        raise ValueError("NOT_SOLELY_MISSING_ONE_TITLE_VARIANT")
    # A literal transcript fragment is genuine speech but NOT an approved
    # SEO topic. Never promote a provisional model/ASR label into a title.
    proposals = [
        r["topic_candidate_not_fact"]
        for r in source.get("records", [])
        if r.get("provisional") is False
        and r.get("incomplete_source_fragment") is not True
        and r.get("context_is_not_speaker_proof") is not True
    ]
    accepted, changed = sanitize_review_variants(
        str(package.get("title") or ""), existing, proposals)
    if not changed or len(accepted) != 3:
        raise ValueError("NO_GROUNDED_THIRD_AB_TITLE")
    corrected_package = dict(package)
    corrected_package["title_variants"] = accepted
    result = inspect_package(corrected_package)
    if not result["format_pass"]:
        raise ValueError("REPAIRED_SEO_FORMAT_INVALID")
    output = dict(draft)
    output["seo"] = corrected_package
    output["quality_checks"] = {**result,
        "unsupported_numbers": draft.get("quality_checks", {}).get("unsupported_numbers", [])}
    if output["quality_checks"]["unsupported_numbers"]:
        raise ValueError("REPAIRED_SEO_UNSUPPORTED_NUMBERS")
    output["blockers"] = ["SOURCE_VARIANT_REQUIRES_INDEPENDENT_CHECK"]
    output["status"] = "READY_FOR_INDEPENDENT_AI_REVIEW"
    output["repair_method"] = "exact_source_topic_title_only"
    output["independent_recheck_required"] = True
    output["human_approved"] = False
    output["g3_accepted"] = False
    output["publication_allowed"] = False
    return output
