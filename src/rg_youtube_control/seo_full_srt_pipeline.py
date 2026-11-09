"""Universal sequential SEO flow from the *complete* original SRT.

A model must inspect every source window and return traceable, literal
candidates before any title or description is composed. All outputs remain
review-only; no metadata or source video is ever modified.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .seo_full_srt_topics import analyze_full_original_transcript, split_transcript_windows
from .seo_g3_batch_drafts import (
    prepare_source_packet, draft_seo_package, evaluate_independent_draft,
    repair_seo_package,
)

Chat = Callable[[list[dict[str, str]]], str]



def select_grounded_highlights(
    *, windows: list[dict[str, Any]],
    topics_by_window: dict[int, list[dict[str, Any]]],
    chat: Chat, limit: int = 12,
) -> tuple[list[tuple[int, dict[str, Any]]], list[int]]:
    """Select representative SRT topics in a bounded hierarchical tournament.

    Every original topical window is presented to the model in round one.
    No LLM request includes more than four windows or twelve source topics;
    long streams cannot overflow a final 4096-token selection prompt.
    """
    present = sorted(i for i in topics_by_window if topics_by_window[i])
    if len(present) <= limit:
        return [(i, topics_by_window[i][0]) for i in present], present
    if not 2 <= limit <= 12:
        raise ValueError("INVALID_HIGHLIGHT_LIMIT")
    candidates: list[tuple[int, dict[str, Any]]] = [
        (i, topic) for i in present for topic in topics_by_window[i][:3]
    ]
    original_windows_seen: set[int] = set()
    first_round = True
    while len(candidates) > limit:
        # First pass groups all candidates from at most FOUR adjacent windows.
        # Later passes group already-selected source topics, max four per call.
        if first_round:
            spans: list[list[tuple[int, dict[str, Any]]]] = []
            for start in range(0, len(present), 4):
                window_group = set(present[start:start + 4])
                group = [x for x in candidates if x[0] in window_group]
                spans.append(group)
                original_windows_seen.update(window_group)
        else:
            group_count = max(limit, (len(candidates) + 3) // 4)
            spans = [
                candidates[round(g * len(candidates) / group_count):
                           round((g + 1) * len(candidates) / group_count)]
                for g in range(group_count)
            ]
        if not spans or any(not group or len(group) > 12 for group in spans):
            raise ValueError("INVALID_HIGHLIGHT_REDUCTION_GROUP")
        reduced: list[tuple[int, dict[str, Any]]] = []
        for group in spans:
            options = [
                {
                    "window_index": window_index,
                    "source_index": topic["source_index"],
                    "topic_candidate_not_fact": topic["topic_candidate_not_fact"],
                    "literal_source_quote_excerpt": topic["source_quote"][:320],
                }
                for window_index, topic in group
            ]
            prompt = {
                "task": "Choose ONE strongest concrete discussion subject for YouTube metadata from the provided original SRT citations.",
                "rules": [
                    "Return only JSON {source_index: integer}, using an ID present in these options.",
                    "Prefer specific, distinctive discussion topics over jokes, greetings and vague dialogue.",
                    "Never invent quotes, identities, events or factual interpretations.",
                    "A participant's statement is not proof of an external fact.",
                ],
                "options": options,
            }
            raw = chat([
                {"role": "system", "content": "Український редактор. Обери тільки один наявний індекс цитати. Поверни JSON."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ])
            try:
                answer = json.loads(str(raw).strip())
            except (TypeError, ValueError):
                raise ValueError("INVALID_HIGHLIGHT_SELECTOR_REPLY") from None
            selected_id = answer.get("source_index") if isinstance(answer, dict) else None
            if type(selected_id) is not int:
                raise ValueError("INVALID_HIGHLIGHT_SELECTOR_INDEX")
            matches = [part for part in group
                       if part[1]["source_index"] == selected_id]
            if len(matches) != 1:
                raise ValueError("HIGHLIGHT_SELECTOR_NOT_IN_SOURCE")
            reduced.append(matches[0])
        if len(reduced) >= len(candidates):
            raise ValueError("HIGHLIGHT_REDUCTION_DID_NOT_PROGRESS")
        candidates = reduced
        first_round = False
    if original_windows_seen != set(present):
        raise ValueError("HIGHLIGHT_WINDOW_COVERAGE_MISMATCH")
    candidates.sort(key=lambda pair: (pair[0], pair[1]["start_s"]))
    return candidates, present


def source_packet_from_complete_map(
    *, video_id: str, original_rows: list[dict[str, Any]],
    full_map: dict[str, Any], max_chars: int = 3200,
    selector: Chat | None = None,
) -> dict[str, Any]:
    """Select a literal-source topic from EACH substantive transcript window.

    Unreviewed windows are never silently omitted, and no semantic topic is
    described as an established historical or political fact.
    """
    windows = split_transcript_windows(original_rows, max_chars=max_chars)
    if (full_map.get("schema") != "RG_FULL_SRT_TOPIC_MAP_V1"
            or full_map.get("all_nonempty_cues_covered") is not True
            or full_map.get("window_count") != len(windows)
            or full_map.get("source_cues_processed") != sum(w["cue_count"] for w in windows)):
        raise ValueError("FULL_SOURCE_COVERAGE_REQUIRED")
    proposals = full_map.get("topic_records_review_only") or []
    per_window: dict[int, list[dict[str, Any]]] = {}
    for item in proposals:
        if not isinstance(item, dict) or type(item.get("window_index")) is not int:
            raise ValueError("INVALID_FULL_SOURCE_TOPIC")
        window_index = item["window_index"]
        if window_index not in range(len(windows)):
            raise ValueError("INVALID_FULL_SOURCE_WINDOW")
        per_window.setdefault(window_index, []).append(item)
    cards: list[dict[str, Any]] = []
    unaddressed = set(range(len(windows))) - set(per_window)
    documented_empty = set(full_map.get("windows_without_substantive_topics") or [])
    if unaddressed != documented_empty:
        raise ValueError("UNDOCUMENTED_TOPICAL_WINDOW")
    # Keep one source-backed theme from EVERY substantive window first,
    # then spend spare prompt capacity on a second theme per window.
    # A first-topic-only selection misses distinct subjects in real dialogues.
    # A source cue shorter than 8 characters cannot form a valid G3 card.
    # Fall back to another independently extracted literal theme from the
    # same window instead of failing the whole video on a one-word fragment.
    unusable_windows: list[int] = []
    eligible: dict[int, list[dict[str, Any]]] = {}
    for window_index, candidates in per_window.items():
        usable = [
            candidate for candidate in candidates
            if len(str(candidate.get("source_quote") or "").strip()) >= 8
            and len(str(candidate.get("topic_candidate_not_fact") or "").strip()) >= 5
        ]
        if usable:
            eligible[window_index] = usable
        else:
            unusable_windows.append(window_index)
    per_window = eligible
    present = [i for i in range(len(windows)) if per_window.get(i)]
    # The full SRT is analyzed before this selection. A 4096-token final
    # synthesis cannot carry all themes from an arbitrarily long stream.
    # Select chronologically across the WHOLE video, record omitted windows,
    # and block any AI quality PASS until all topical windows are covered.
    full_selector_coverage = False
    if len(present) > 12 and selector is not None:
        selected_topics, considered_windows = select_grounded_highlights(
            windows=windows, topics_by_window=per_window,
            chat=selector, limit=12)
        selected_windows = [idx for idx, _ in selected_topics]
        full_selector_coverage = considered_windows == present
    elif len(present) > 12:
        indices = [round(i * (len(present) - 1) / 11) for i in range(12)]
        selected_windows = [present[i] for i in indices]
        selected_topics = [(i, per_window[i][0]) for i in selected_windows]
    else:
        selected_windows = present
        selected_topics = [(i, per_window[i][0]) for i in present]
        for i in present:
            if len(selected_topics) >= 12:
                break
            if len(per_window[i]) > 1:
                selected_topics.append((i, per_window[i][1]))
    omitted_windows = sorted(set(present) - set(selected_windows))
    selected_topics.sort(key=lambda part: (part[0], part[1]["start_s"]))
    for i, chosen in selected_topics:
        window = windows[i]
        ix = chosen.get("source_index")
        cue_items = window["cues"]
        index = next((j for j, c in enumerate(cue_items)
                      if c["source_index"] == ix), -1)
        if index < 0 or cue_items[index]["text"] != chosen.get("source_quote"):
            raise ValueError("FULL_MAP_QUOTE_NOT_IN_SOURCE")
        quote = cue_items[index]["text"]
        context = " ".join(x["text"] for x in cue_items[max(0,index-2):index+3])
        if quote not in context:
            raise ValueError("FULL_MAP_CONTEXT_INTEGRITY")
        cards.append({
            "video_id": video_id, "record_id": len(cards)+1,
            "start_s": cue_items[index]["start_s"],
            "source_quote": quote,
            "source_context": context,
            "candidate_topic": chosen["topic_candidate_not_fact"],
            "status": "PROVISIONAL_SOURCE_REVIEW",
            "publication_allowed": False,
        })
    if not cards:
        raise ValueError("NO_SUBSTANTIVE_SOURCE_THEME")
    if len(cards) > 12:
        raise ValueError("SOURCE_MAP_TOO_LONG_FOR_ONE_SEO_SYNTHESIS")
    packet = prepare_source_packet(video_id=video_id, cards=cards, max_cards=12)
    packet["full_srt_cues_processed"] = full_map["source_cues_processed"]
    packet["source_topics_selected"] = len(cards)
    packet["source_topic_candidates_total"] = len(proposals)
    packet["source_topics_omitted_from_synthesis"] = len(proposals) - len(cards)
    packet["full_srt_windows_processed"] = len(windows)
    packet["source_windows_in_synthesis"] = selected_windows
    packet["source_windows_omitted_from_synthesis"] = omitted_windows
    packet["topical_synthesis_complete"] = bool(
        not omitted_windows or full_selector_coverage)
    packet["all_topical_windows_considered_for_highlights"] = bool(
        not omitted_windows or full_selector_coverage)
    packet["windows_without_substantive_topics"] = sorted(documented_empty)
    packet["windows_with_only_short_topics"] = sorted(unusable_windows)
    packet["topical_synthesis_complete"] = bool(
        (not omitted_windows or full_selector_coverage) and not unusable_windows)
    packet["full_srt_coverage"] = True
    packet["publication_allowed"] = False
    return packet


def generate_review_only_seo_from_full_srt(
    *, video_id: str, original_rows: list[dict[str, Any]],
    writer: Chat, critic: Chat, max_chars: int = 3200,
) -> dict[str, Any]:
    """Generate, critique and perform ONE bounded repair from full SRT.

    No automatic publication or editorial approval even if independent AI
    finds no issue. Original caption rows are never changed.
    """
    full_map = analyze_full_original_transcript(
        original_rows, chat=writer, max_chars=max_chars)
    packet = source_packet_from_complete_map(
        video_id=video_id, original_rows=original_rows,
        full_map=full_map, max_chars=max_chars,
        selector=writer)
    initial = draft_seo_package(source=packet, chat=writer)
    review = evaluate_independent_draft(draft=initial, source=packet, chat=critic)
    result: dict[str, Any] = {
        "schema": "RG_FULL_SRT_G3_BATCH_RESULT_V1",
        "video_id": video_id, "source_map": full_map, "source_packet": packet,
        "initial": initial, "initial_review": review,
        "publication_allowed": False, "human_approved": False,
    }
    if initial["status"] != "READY_FOR_INDEPENDENT_AI_REVIEW" or review["issues"]:
        corrected = repair_seo_package(
            source=packet, previous=initial, critique=review, chat=writer)
        second_review = evaluate_independent_draft(
            draft=corrected, source=packet, chat=critic)
        result["repaired"] = corrected
        result["repaired_review"] = second_review
        selected, selected_review = corrected, second_review
    else:
        selected, selected_review = initial, review
    result["ai_screened"] = bool(
        selected["quality_checks"].get("format_pass")
        and not selected["quality_checks"].get("unsupported_numbers")
        and not selected_review["issues"]
        and selected_review["risk_ai"] == "low"
        and not full_map["windows_without_substantive_topics"]
        and packet["topical_synthesis_complete"]
    )
    result["editorial_approved"] = False
    result["publication_allowed"] = False
    return result
