"""Universal transcript-to-SEO v2, deliberately independent of legacy generator.

The model extracts and writes; deterministic code checks quote provenance,
model outputs and source coverage. No topic-specific dictionaries and no
publishing permissions. The caller supplies a local JSON chat function.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .seo_v2_evidence import Cue, evidence_ledger, make_windows, parse_srt, verify_quote
from .seo_quality_gate import inspect_editorial_targets, inspect_package

Chat = Callable[[str], dict[str, Any]]


def _ask(chat: Chat, prompt: str) -> dict[str, Any]:
    reply = chat(prompt)
    if isinstance(reply, str):
        reply = json.loads(reply)
    if not isinstance(reply, dict):
        raise ValueError("Local model must return a JSON object")
    return reply


def _source_numbers(cues: list[Cue]) -> set[str]:
    # Avoid SRT timestamps and indexing: only spoken cue text.
    return set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)",
                          " ".join(cue.text for cue in cues)))


def _draft_numbers(draft: dict[str, Any]) -> set[str]:
    fields = [str(draft.get("title") or ""),
              str(draft.get("description") or ""),
              *[str(t) for t in draft.get("title_variants") or []],
              *[str(t) for t in draft.get("tags") or []]]
    return set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", " ".join(fields)))


def _parse_proposals(raw: dict[str, Any], indices: list[int]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for item in raw.get("quotes") or []:
        if not isinstance(item, dict):
            continue
        try:
            cited_indices = [int(i) for i in item.get("cue_indices") or []]
        except (ValueError, TypeError):
            continue
        if not cited_indices or any(i not in indices for i in cited_indices):
            continue
        proposals.append({
            "quote": str(item.get("quote") or ""),
            "cue_indices": cited_indices,
        })
    return proposals


def _fallback_window_quotes(cues: list[Cue], indices: list[int],
                            *, max_quotes: int = 3) -> list[dict[str, Any]]:
    """Provide literal SRT evidence when a model skips a source window.

    These are source extracts, not LLM-verified important claims. Choose
    different parts of the window without guessing its subject.
    """
    if not indices or max_quotes < 1:
        return []
    count = min(max_quotes, len(indices))
    candidates: list[dict[str, Any]] = []
    chosen: set[int] = set()
    for segment in range(count):
        left = segment * len(indices) // count
        right = (segment + 1) * len(indices) // count
        subset = indices[left:max(left + 1, right)]
        # A moderately substantial spoken statement is better than a filler.
        ordered = sorted(
            subset,
            key=lambda i: (
                len(cues[i].text) < 24,
                -min(len(cues[i].text), 240),
                i,
            ),
        )
        for idx in ordered:
            if idx in chosen:
                continue
            raw_text = cues[idx].text
            excerpt = (raw_text if len(raw_text) <= 240 else
                       raw_text[:240].rsplit(" ", 1)[0]).strip()
            if len(excerpt) < 8:
                continue
            proposal = {"quote": excerpt, "cue_indices": [idx]}
            if verify_quote(excerpt, cues, [idx]) is not None:
                candidates.append(proposal)
                chosen.add(idx)
                break
    return candidates


def _extract(cues: list[Cue], chat: Chat) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    proposals: list[dict[str, Any]] = []
    windows = make_windows(cues)
    failed_windows: list[int] = []
    for window_index, indices in enumerate(windows):
        captions = [
            {"cue": i, "text": cues[i].text}
            for i in indices
        ]
        prompt = (
            "Extract up to three substantial verbatim statements from the "
            "provided subtitle cues. Every quote must be an exact continuous "
            "passage from one cue or up to three adjacent cues, retaining "
            "the original language. Avoid short fillers, isolated words, "
            "assumed speakers or interpreted events. Return JSON only: "
            "{\"quotes\":[{\"quote\":\"literal source words\","
            "\"cue_indices\":[0]}]}. No topic titles, no inferred claims.\n"
            "SOURCE CUES:\n" + json.dumps(captions, ensure_ascii=False)
        )
        candidates = _parse_proposals(_ask(chat, prompt), indices)
        verified_model_quotes = [
            item for item in candidates
            if verify_quote(item["quote"], cues, item["cue_indices"]) is not None
        ]
        if len(verified_model_quotes) < 2:
            failed_windows.append(window_index)
            # Fill from the actual recording, not an inferred model topic.
            # Keep all invalid model proposals visible to the audit ledger.
            for literal in _fallback_window_quotes(cues, indices):
                if len(verified_model_quotes) >= 2:
                    break
                proof = verify_quote(literal["quote"], cues, literal["cue_indices"])
                if proof is not None and proof.evidence_id not in {
                    verify_quote(item["quote"], cues, item["cue_indices"]).evidence_id
                    for item in verified_model_quotes
                }:
                    verified_model_quotes.append(literal)
                    candidates.append(literal)
        proposals.extend(candidates)
    ledger = evidence_ledger(cues, proposals)
    ledger["deterministic_fallback_windows"] = failed_windows
    # A returned quote still needs deterministic verification. A fabricated
    # quote must not make a source window look covered.
    covered = {
        i for evidence in ledger["accepted"] for i in evidence["cue_indices"]
    }
    uncovered = [
        n for n, positions in enumerate(windows)
        if not any(i in covered for i in positions)
    ]
    ledger["analysis_windows_total"] = len(windows)
    ledger["windows_without_quotes"] = uncovered
    ledger["source_cues_with_evidence"] = len(covered)
    ledger["review_required"] = bool(
        ledger["review_required"] or uncovered
    )
    return ledger, [
        {"start_ms": cues[indices[0]].start_ms,
         "end_ms": cues[indices[-1]].end_ms,
         "first_index": indices[0],
         "last_index": indices[-1]}
        for indices in windows
    ]


def _select_topics(ledger: dict[str, Any], chat: Chat) -> list[dict[str, Any]]:
    """Bounded semantic map/reduce across any recording length.

    Each model call sees at most 16 literal quotations. The merge call only
    sees candidate labels and original IDs, never model-generated summaries
    masquerading as proven facts.
    """
    evidence = ledger["accepted"]
    if not evidence:
        return []
    ids = {row["evidence_id"] for row in evidence}

    def parse_topics(raw: dict[str, Any], allowed: set[str],
                     maximum: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in raw.get("topics") or []:
            if not isinstance(item, dict):
                continue
            cited = list(dict.fromkeys(
                str(i) for i in item.get("evidence_ids") or []
                if str(i) in allowed
            ))
            label = str(item.get("label_uk") or "").strip()
            if cited and 3 <= len(label) <= 100:
                results.append({"label_uk": label, "evidence_ids": cited})
            if len(results) >= maximum:
                break
        return results

    candidates: list[dict[str, Any]] = []
    for offset in range(0, len(evidence), 16):
        chunk = evidence[offset:offset + 16]
        prompt = (
            "Classify the main topics of this portion of an arbitrary "
            "conversation, in Ukrainian. No assumptions about channel, "
            "politics or any predefined category. Each proposed topic MUST "
            "cite one or more exact evidence_id values from this list. "
            "Return JSON: {\"topics\":[{\"label_uk\":\"...\", "
            "\"evidence_ids\":[\"ev_...\"]}]}. "
            "Prefer 1-4 meaningful topics. Do not fabricate events.\n"
            "VERBATIM EVIDENCE:\n" + json.dumps(chunk, ensure_ascii=False)
        )
        candidates.extend(parse_topics(
            _ask(chat, prompt),
            {item["evidence_id"] for item in chunk},
            maximum=4,
        ))

    # Keep the reducer prompt bounded even with hundreds of timeline blocks.
    # Merge intermediate candidates in small consecutive batches until five
    # grounded subjects remain. Each pass retains only existing source IDs.
    rounds = 0
    while len(candidates) > 5:
        rounds += 1
        if rounds > 16:
            raise ValueError("Semantic topic reduction exceeded safety bound")
        next_candidates: list[dict[str, Any]] = []
        for offset in range(0, len(candidates), 12):
            batch = candidates[offset:offset + 12]
            allowed = {i for item in batch for i in item["evidence_ids"]}
            prompt = (
                "Merge overlapping topics of this arbitrary video into up to "
                "4 precise Ukrainian subject labels. Keep the real original "
                "evidence_ids, do not add new ones or infer claims. "
                "Return JSON: {\"topics\":[{\"label_uk\":\"...\", "
                "\"evidence_ids\":[\"ev_...\"]}]}.\nTOPIC MAP:\n"
                + json.dumps(batch, ensure_ascii=False)
            )
            merged = parse_topics(_ask(chat, prompt), allowed, maximum=4)
            if not merged:
                # Do not silently discard source coverage when a model gives
                # invalid reduction JSON. Preserve the candidate for review.
                merged = batch[:4]
            next_candidates.extend(merged)
        if len(next_candidates) >= len(candidates) and len(candidates) > 5:
            raise ValueError("Semantic reducer did not reduce topic count")
        candidates = next_candidates

    return [
        {**item, "rank": rank}
        for rank, item in enumerate(candidates[:5], 1)
        if all(i in ids for i in item["evidence_ids"])
    ]


def _proof_index(
    ledger: dict[str, Any],
    topics: list[dict[str, Any]],
    *,
    max_quotes: int = 24,
    max_chars: int = 12000,
) -> list[dict[str, Any]]:
    """Bounded evidence for the writer, preserving theme and timeline spread.

    The full immutable ledger remains available for audit. The writer sees
    a representative sample, never a misleading claim that the full SRT
    fits its context window.
    """
    by_id = {row["evidence_id"]: row for row in ledger["accepted"]}
    if not by_id:
        return []
    ordered: list[dict[str, Any]] = []
    used: set[str] = set()
    for topic in topics:
        for evidence_id in topic["evidence_ids"]:
            if evidence_id in by_id and evidence_id not in used:
                ordered.append(by_id[evidence_id])
                used.add(evidence_id)
    if not ordered:
        return []
    if len(ordered) <= max_quotes and len(json.dumps(
        ordered, ensure_ascii=False
    )) <= max_chars:
        return ordered

    # Reserve at least one point from each named subject and both ends of
    # the recording; sample remaining evidence evenly over source time.
    first_per_topic: list[dict[str, Any]] = []
    for topic in topics:
        candidates = [
            by_id[eid] for eid in topic["evidence_ids"]
            if eid in by_id
        ]
        if candidates:
            first_per_topic.append(candidates[0])
    chronological = sorted(ordered, key=lambda item: (
        item["start_ms"], item["end_ms"]
    ))
    priority = [
        *first_per_topic,
        chronological[0],
        chronological[-1],
    ]
    target = min(max_quotes, len(ordered))
    if target > 1:
        priority.extend(
            chronological[round(i * (len(chronological) - 1) / (target - 1))]
            for i in range(target)
        )
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in priority:
        eid = item["evidence_id"]
        if eid in seen:
            continue
        trial = selected + [item]
        if len(trial) > max_quotes or len(json.dumps(
            trial, ensure_ascii=False
        )) > max_chars:
            continue
        seen.add(eid)
        selected.append(item)
    return selected




def _draft(topics: list[dict[str, Any]], proof: list[dict[str, Any]],
           chat: Chat) -> dict[str, Any]:
    instruction = (
        "You are an accurate Ukrainian YouTube editor. Produce ONE primary "
        "headline, exactly THREE genuinely distinct A/B headlines, a "
        "400-900-character meaningful Ukrainian description, and 8-15 "
        "specific search tags. Work ONLY from the citation IDs and literal "
        "quotes below. The first ranked topic is the central subject. "
        "You may vary the angle but cannot invent events, motivations, "
        "numbers, outcomes or turn someone's opinion into established fact. "
        "If the source cannot support the requirements, return fewer tags "
        "or a shorter description; the result will be flagged for review, "
        "not padded with generic content. Return JSON with keys title, "
        "variant_evidence, description, tag_evidence, support_ids. "
        "variant_evidence must be an array of exactly three objects "
        "{text: Ukrainian A/B headline, evidence_ids: [exact source IDs]}. "
        "Put each headline and its supporting IDs in the SAME object. "
        "tag_evidence must be an array of objects with {tag: Ukrainian "
        "search phrase, evidence_ids: [exact source IDs]}. Put each tag "
        "and its supporting IDs in the SAME object, not separate arrays. "
        "support_ids must contain title (ID array), title_variants "
        "(array of ID arrays), and description (ID array). "
        "An unsupported phrase needs an EMPTY citation list and will be "
        "flagged for human review. No general keyword padding. "
        "All supported content must be sourced from actual quotations.\n"
        "TOPICS:\n" + json.dumps(topics, ensure_ascii=False)
        + "\nQUOTES:\n" + json.dumps(proof, ensure_ascii=False)
    )
    output = _ask(chat, instruction)
    # Pair each title/variant with its citation at generation time,
    # avoiding drift across parallel arrays in local model JSON.
    variant_pairs = output.get("variant_evidence")
    if isinstance(variant_pairs, list):
        variants: list[str] = []
        groups: list[list[str]] = []
        for item in variant_pairs[:3]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("text") or "").strip()
            if not title:
                continue
            ids = item.get("evidence_ids")
            variants.append(title)
            groups.append(ids if isinstance(ids, list) else [])
        if variants:
            output["title_variants"] = variants
            support = output.get("support_ids")
            if not isinstance(support, dict):
                support = {}
            support["title_variants"] = groups
            output["support_ids"] = support
    # Canonical paired tags avoid a model shifting evidence lists.
    pairs = output.get("tag_evidence")
    if isinstance(pairs, list):
        tags: list[str] = []
        groups: list[list[str]] = []
        for item in pairs[:15]:
            if not isinstance(item, dict):
                continue
            value = str(item.get("tag") or "").strip()
            if not value:
                continue
            ids = item.get("evidence_ids")
            tags.append(value)
            groups.append(ids if isinstance(ids, list) else [])
        if tags:
            output["tags"] = tags
            support = output.get("support_ids")
            if not isinstance(support, dict):
                support = {}
            support["tags"] = groups
            output["support_ids"] = support
    return output


def _repair_source_citations(
    draft: dict[str, Any], proof: list[dict[str, Any]], chat: Chat,
) -> bool:
    """One bounded repair of missing evidence-ID arrays, not creative SEO.

    A model may return an attractive draft but omit a parallel citation for
    one tag. The repair prompt can ONLY supply ID arrays for existing text.
    It cannot rewrite or fabricate an additional assertion.
    """
    ids = {item["evidence_id"] for item in proof}
    support = draft.get("support_ids")
    if not isinstance(support, dict):
        support = {}

    def is_valid() -> bool:
        for field in ("title", "description"):
            values = support.get(field)
            if not isinstance(values, list) or not values or any(
                not isinstance(value, str) or value not in ids for value in values
            ):
                return False
        for field in ("title_variants", "tags"):
            entries = draft.get(field)
            values = support.get(field)
            if not isinstance(entries, list) or not isinstance(values, list):
                return False
            if len(entries) != len(values):
                return False
            if any(
                not isinstance(group, list) or not group or any(
                    not isinstance(value, str) or value not in ids
                    for value in group
                ) for group in values
            ):
                return False
        return True

    if is_valid():
        return False
    # First repair the most common structured-output defect separately:
    # one missing/invalid citation per tag. This is a small matching task,
    # not another generation of the whole SEO package.
    tags = draft.get("tags")
    tag_groups = support.get("tags")
    tag_invalid = (
        isinstance(tags, list) and (
            not isinstance(tag_groups, list)
            or len(tag_groups) != len(tags)
            or any(
                not isinstance(group, list) or not group
                or any(not isinstance(eid, str) or eid not in ids
                       for eid in group)
                for group in tag_groups
            )
        )
    )
    if tag_invalid:
        focused = (
            "You ONLY match existing Ukrainian search tags to verbatim "
            "quotes. Do not invent a tag, entity, event, person or evidence "
            "ID. Return JSON with exactly one key tags: an ARRAY of "
            "evidence-ID arrays, one for EACH input tag in the same order. "
            "Use [] if no quotation supports that tag. "
            "Never attach a random ID to satisfy length. "
            "TAGS:\\n" + json.dumps(tags, ensure_ascii=False)
            + "\\nEVIDENCE:\\n" + json.dumps([
                {"id": entry["evidence_id"], "quote": entry["quote"]}
                for entry in proof
            ], ensure_ascii=False)
        )
        try:
            candidate_groups = _ask(chat, focused).get("tags")
        except (ValueError, RuntimeError, TypeError, TimeoutError):
            candidate_groups = None
        if (
            isinstance(candidate_groups, list)
            and len(candidate_groups) == len(tags)
            and all(
                isinstance(group, list) and bool(group)
                and all(isinstance(eid, str) and eid in ids for eid in group)
                for group in candidate_groups
            )
        ):
            support["tags"] = candidate_groups
            draft["support_ids"] = support
            if is_valid():
                return True
    request = (
        "You are a source-citation matcher, NOT an SEO writer. "
        "Do not change any existing title, variant, sentence or tag. "
        "Find which exact verbatim quotations support each existing field. "
        "Return ONLY JSON with support_ids containing title (ID array), "
        "description (ID array), title_variants (array of ID arrays), "
        "and tags (array of ID arrays in exactly the same order). "
        "If a phrase has no supporting quotation, return [] for its field "
        "or list element. NEVER assign a random ID to satisfy a schema. "
        "Review-only; no automatic publication.\n"
        "DRAFT:\n" + json.dumps({
            key: draft.get(key) for key in (
                "title", "title_variants", "description", "tags"
            )
        }, ensure_ascii=False)
        + "\nLITERAL EVIDENCE:\n"
        + json.dumps(proof, ensure_ascii=False)
    )
    try:
        response = _ask(chat, request)
    except (ValueError, RuntimeError, TypeError, TimeoutError):
        # Bad citation JSON cannot invalidate an otherwise useful draft.
        # The regular gate still reports its original missing citations.
        return False
    candidate = response.get("support_ids")
    if not isinstance(candidate, dict):
        return False
    original = support
    support = candidate
    if is_valid():
        draft["support_ids"] = candidate
        return True
    support = original
    return False


def validate_draft(draft: dict[str, Any], ledger: dict[str, Any],
                   cues: list[Cue],
                   allowed_ids: set[str] | None = None) -> dict[str, Any]:
    """Mechanical checks, NOT semantic fact approval."""
    ids = (
        allowed_ids if allowed_ids is not None
        else {row["evidence_id"] for row in ledger["accepted"]}
    )
    support = draft.get("support_ids") or {}
    issues: list[str] = []
    if not isinstance(support, dict):
        support = {}
    for field in ("title", "description"):
        cited = support.get(field) or []
        if not isinstance(cited, list) or not cited or any(i not in ids for i in cited):
            issues.append(field.upper() + "_UNSUPPORTED")
    for field, values in (("title_variants", draft.get("title_variants") or []),
                          ("tags", draft.get("tags") or [])):
        groups = support.get(field)
        if not isinstance(groups, list) or len(groups) != len(values):
            issues.append(field.upper() + "_CITATIONS_MISSING")
        elif any(not isinstance(group, list) or not group or
                 any(i not in ids for i in group) for group in groups):
            issues.append(field.upper() + "_UNSUPPORTED")
    unsupported = sorted(_draft_numbers(draft) - _source_numbers(cues))
    if unsupported:
        issues.append("UNSUPPORTED_NUMBERS")
    fields = {
        "title": draft.get("title"),
        "title_variants": draft.get("title_variants"),
        "description": draft.get("description"),
        "tags": draft.get("tags"),
    }
    format_gate = inspect_package(fields)
    editorial_gate = inspect_editorial_targets(fields)
    if not format_gate["format_pass"]:
        issues.append("FORMAT_GATE_FAILED")
    if not editorial_gate["editorial_gate_pass"]:
        issues.append("EDITORIAL_GATE_FAILED")
    if not ledger["accepted"]:
        issues.append("NO_VERIFIED_SOURCE_QUOTES")
    if ledger.get("windows_without_quotes"):
        issues.append("TRANSCRIPT_WINDOWS_WITHOUT_EVIDENCE")
    # Rejected *proposals* are not used as evidence and must not invalidate
    # correctly verified quotes in the final draft. Preserve a separate
    # warning so extraction quality stays visible to the human editor.
    extraction_warnings: list[str] = []
    if ledger.get("rejected"):
        extraction_warnings.append("INVALID_QUOTE_PROPOSALS_DISCARDED")
    if ledger.get("deterministic_fallback_windows"):
        extraction_warnings.append("LITERAL_FALLBACK_EVIDENCE_USED")
    return {
        "issues": sorted(set(issues)),
        "extraction_warnings": extraction_warnings,
        "format": format_gate,
        "editorial": editorial_gate,
        "source_ids_valid": not any("UNSUPPORTED" in i or "CITATIONS" in i
                                    for i in issues),
        # Mechanical citation membership is not semantic entailment.
        "semantic_review_required": True,
        "publication_allowed": False,
    }


def generate_universal_seo(srt: str, chat: Chat,
                           independent_review: Chat | None = None) -> dict[str, Any]:
    """Run independent modules on ANY SRT. Never publish or declare approval."""
    cues = parse_srt(srt)
    ledger, windows = _extract(cues, chat)
    topics = _select_topics(ledger, chat)
    proof = _proof_index(ledger, topics)
    if not proof:
        return {
            "status": "INSUFFICIENT_VERIFIED_EVIDENCE", "draft": None,
            "evidence": ledger, "windows": windows, "topics": topics,
            "publication_allowed": False,
        }
    # All topic IDs shown to the writer must actually be in its bounded
    # evidence excerpt. Otherwise the writer could cite invisible sources.
    visible_ids = {item["evidence_id"] for item in proof}
    visible_topics = [
        {**topic, "evidence_ids": [
            eid for eid in topic["evidence_ids"] if eid in visible_ids
        ]}
        for topic in topics
    ]
    visible_topics = [topic for topic in visible_topics if topic["evidence_ids"]]
    draft = _draft(visible_topics, proof, chat)
    citations_repaired = _repair_source_citations(draft, proof, chat)
    from .seo_v2_refine import repair_editorial_fields
    draft, repaired_fields = repair_editorial_fields(
        draft, proof, chat, spoken_numbers=_source_numbers(cues),
    )
    gate = validate_draft(draft, ledger, cues, allowed_ids=visible_ids)
    from .seo_v2_semantic import (
        independent_review as check_semantics,
        revise_semantic_defects,
        unsupported_names,
    )
    name_warnings = unsupported_names(draft, proof)
    if name_warnings:
        gate["issues"] = sorted(set([
            *gate["issues"], "UNVERIFIED_NAMED_ENTITIES"
        ]))
        gate["unverified_names"] = name_warnings
    independent = None
    semantic_repair_applied = False
    if independent_review is not None:
        try:
            independent = check_semantics(draft, proof, independent_review)
        except (ValueError, RuntimeError, TypeError, TimeoutError):
            independent = {"issues": [{
                "field": "reviewer",
                "reason": "INDEPENDENT_REVIEW_UNAVAILABLE",
            }], "review_status": "FAILED_CLOSED"}
        # A language model can overlook a misspelled name while
        # reviewing the explanation. Inject deterministic name defects
        # into the editor's correction brief, field by field.
        if name_warnings:
            existing = list(independent.get("issues") or [])
            for field in ("title", "title_variants", "description", "tags"):
                field_copy = {
                    "title": "", "title_variants": [],
                    "description": "", "tags": [],
                }
                field_copy[field] = draft.get(field)
                field_names = unsupported_names(field_copy, proof)
                if field_names:
                    existing.append({
                        "field": field,
                        "reason": (
                            "Unconfirmed personal-name spelling in verbatim SRT: "
                            + ", ".join(field_names)
                            + ". Do not guess a replacement identity."
                        ),
                    })
            independent["issues"] = existing
        # Validate separately: a bad description must not throw away a
        # proven title fix. Each field receives one bounded attempt, and
        # a fresh independent check must clear that particular defect.
        from .seo_v2_revision_loop import repair_fields_independently

        def recheck(candidate: dict[str, Any]) -> dict[str, Any]:
            report = validate_draft(
                candidate, ledger, cues, allowed_ids=visible_ids,
            )
            invalid_names = unsupported_names(candidate, proof)
            if invalid_names:
                report["issues"] = sorted(set([
                    *report["issues"], "UNVERIFIED_NAMED_ENTITIES"
                ]))
                report["unverified_names"] = invalid_names
            return report

        semantic_repaired_fields: list[str] = []
        if independent.get("issues"):
            draft, gate, independent, semantic_repaired_fields = (
                repair_fields_independently(
                    draft, proof, independent, chat, independent_review,
                    recheck,
                )
            )
            semantic_repair_applied = bool(semantic_repaired_fields)
    return {
        "status": ("REVIEW_REQUIRED" if gate["issues"] or independent is None
                   or independent.get("issues") else "READY_FOR_HUMAN_REVIEW"),
        "draft": {key: draft.get(key) for key in (
            "title", "title_variants", "description", "tags", "support_ids")},
        "gate": gate,
        "citations_repaired": citations_repaired,
        "repaired_fields": repaired_fields,
        "semantic_repair_applied": semantic_repair_applied,
        "semantic_repaired_fields": semantic_repaired_fields if independent_review is not None else [],
        "independent_review": independent,
        "topics": topics, "evidence": ledger, "windows": windows,
        "writer_evidence_quotes": len(proof),
        "full_evidence_quotes": len(ledger["accepted"]),
        "publication_allowed": False,
        "editorial_approved": False,
    }
