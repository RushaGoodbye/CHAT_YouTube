"""Universal transcript-to-SEO v2, deliberately independent of legacy generator.

The model extracts and writes; deterministic code checks quote provenance,
model outputs and source coverage. No topic-specific dictionaries and no
publishing permissions. The caller supplies a local JSON chat function.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .seo_v2_evidence import Cue, evidence_ledger, make_windows, parse_srt
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


def _extract(cues: list[Cue], chat: Chat) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    proposals: list[dict[str, Any]] = []
    windows = make_windows(cues)
    for indices in windows:
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
        proposals.extend(_parse_proposals(_ask(chat, prompt), indices))
    return evidence_ledger(cues, proposals), [
        {"start_ms": cues[indices[0]].start_ms,
         "end_ms": cues[indices[-1]].end_ms,
         "first_index": indices[0],
         "last_index": indices[-1]}
        for indices in windows
    ]


def _select_topics(ledger: dict[str, Any], chat: Chat) -> list[dict[str, Any]]:
    """Semantic map/reduce: model groups citation IDs, never asserts facts."""
    evidence = ledger["accepted"]
    if not evidence:
        return []
    ids = {row["evidence_id"] for row in evidence}
    prompt = (
        "Group these literal source quotations into the main conversation "
        "themes. This can be ANY subject. Never assume the subject of the "
        "channel or invent a quote, speaker or relationship. Rank themes by "
        "importance to the recording, coverage and specificity rather than "
        "generic word counts. Return JSON only with 1-5 topics: "
        "{\"topics\":[{\"label_uk\":\"short Ukrainian subject\","
        "\"evidence_ids\":[\"ev_...\"],\"rank\":1}]}. "
        "Each topic must cite real IDs. No new claims.\nEVIDENCE:\n"
        + json.dumps(evidence, ensure_ascii=False)
    )
    raw = _ask(chat, prompt)
    topics: list[dict[str, Any]] = []
    for item in raw.get("topics") or []:
        if not isinstance(item, dict):
            continue
        citations = list(dict.fromkeys(
            str(i) for i in (item.get("evidence_ids") or []) if str(i) in ids
        ))
        label = str(item.get("label_uk") or "").strip()
        if citations and 3 <= len(label) <= 100:
            topics.append({
                "label_uk": label,
                "evidence_ids": citations,
                "rank": len(topics) + 1,
            })
        if len(topics) >= 5:
            break
    return topics


def _proof_index(ledger: dict[str, Any], topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["evidence_id"]: row for row in ledger["accepted"]}
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for topic in topics:
        for evidence_id in topic["evidence_ids"]:
            if evidence_id not in seen:
                selected.append(by_id[evidence_id])
                seen.add(evidence_id)
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
        "title_variants, description, tags, support_ids. support_ids must "
        "map every field to evidence IDs: title string list, "
        "title_variants array of ID arrays, description array of IDs, "
        "tags array of ID arrays in tag order. "
        "All supported content must be sourced from actual quotations.\n"
        "TOPICS:\n" + json.dumps(topics, ensure_ascii=False)
        + "\nQUOTES:\n" + json.dumps(proof, ensure_ascii=False)
    )
    return _ask(chat, instruction)


def validate_draft(draft: dict[str, Any], ledger: dict[str, Any],
                   cues: list[Cue]) -> dict[str, Any]:
    """Mechanical checks, NOT semantic fact approval."""
    ids = {row["evidence_id"] for row in ledger["accepted"]}
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
    if ledger["review_required"]:
        issues.append("SOURCE_QUOTES_REJECTED_OR_EMPTY")
    return {
        "issues": sorted(set(issues)),
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
    draft = _draft(topics, proof, chat)
    gate = validate_draft(draft, ledger, cues)
    independent = None
    if independent_review is not None:
        independent = _ask(independent_review,
            "Independently review this draft against literal evidence "
            "only. Check unsupported claims, speaker attributions, "
            "semantic relevance and natural Ukrainian. Return JSON: "
            "{\"issues\":[{\"field\":\"...\",\"reason\":\"...\"}]}. "
            "Do not approve publication.\nDRAFT:\n"
            + json.dumps(draft, ensure_ascii=False)
            + "\nEVIDENCE:\n" + json.dumps(proof, ensure_ascii=False))
    return {
        "status": ("REVIEW_REQUIRED" if gate["issues"] or independent is None
                   or independent.get("issues") else "READY_FOR_HUMAN_REVIEW"),
        "draft": {key: draft.get(key) for key in (
            "title", "title_variants", "description", "tags", "support_ids")},
        "gate": gate,
        "independent_review": independent,
        "topics": topics, "evidence": ledger, "windows": windows,
        "publication_allowed": False,
        "editorial_approved": False,
    }
