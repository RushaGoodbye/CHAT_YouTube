"""Full-SRT first pass: chunk each original cue into bounded chronological windows.

Each model-proposed theme must cite an EXACT SRT cue inside its source window.
Original transcripts are never reduced to a handful of early cues before
topic identification. Model claims are not external factual verification.
"""
from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
import json
import math
import re
from typing import Any, Callable

Chat = Callable[[list[dict[str, str]]], str]


def _normalized(text: object) -> str:
    return " ".join(str(text or "").split())


def split_transcript_windows(
    rows: list[dict[str, Any]], *, max_chars: int = 3200,
) -> list[dict[str, Any]]:
    if not 500 <= max_chars <= 12000:
        raise ValueError("INVALID_WINDOW_SIZE")
    if not isinstance(rows, list) or not rows:
        raise ValueError("EMPTY_ORIGINAL_TRANSCRIPT")
    windows: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    length = 0

    def flush() -> None:
        nonlocal current, length
        if not current:
            return
        windows.append({
            "window_index": len(windows),
            "start_s": current[0]["start_s"],
            "end_s": current[-1]["end_s"],
            "cues": current,
            "cue_count": len(current),
            "source_sha256": hashlib.sha256(json.dumps(
                current, sort_keys=True, ensure_ascii=False,
            ).encode("utf-8")).hexdigest(),
        })
        current = []
        length = 0

    previous_start = -1.0
    for original_index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("INVALID_ORIGINAL_CUE")
        try:
            start = float(row["start"])
            duration = float(row.get("duration") or 0)
        except (TypeError, ValueError, KeyError):
            raise ValueError("INVALID_ORIGINAL_CUE_TIME") from None
        if (not math.isfinite(start) or not math.isfinite(duration)
                or start < previous_start or start < 0 or duration < 0):
            raise ValueError("INVALID_ORIGINAL_CUE_ORDER")
        previous_start = start
        quote = _normalized(row.get("text"))
        if not quote:
            # Empty cues are retained as traceable source rows, not evidence.
            continue
        cue = {"source_index": original_index, "start_s": round(start, 3),
               "end_s": round(start + duration, 3), "text": quote}
        cue_size = len(quote) + 35
        if current and length + cue_size > max_chars:
            flush()
        current.append(cue)
        length += cue_size
    flush()
    if not windows:
        raise ValueError("NO_NONEMPTY_ORIGINAL_CUES")
    return windows


def extract_grounded_window_topics(
    window: dict[str, Any], *, chat: Chat,
) -> dict[str, Any]:
    """Propose up to 3 discussion topics, rejecting nonliteral quotes.

    An exact cue ID and original unaltered text are required. The LLM must not
    produce a synthetic quote, guess a speaker or verify real-world events.
    """
    cues = window.get("cues") or []
    if not cues:
        raise ValueError("EMPTY_SOURCE_WINDOW")
    source_by_id = {c["source_index"]: c for c in cues}
    prompt = {
        "task": "Identify up to three substantive discussion themes in the FULL source window.",
        "rules": [
            "Return JSON object: topics array of objects with source_index (integer), quote (EXACT cue text), label_uk (short Ukrainian subject), kind (question|opinion|report|speech).",
            "No invented dates, places, people, outcomes, news or additional claims.",
            "This is a spoken conversation, not a verified news article.",
            "Quote one single original cue exactly; do not concatenate adjacent cues.",
            "Prefer important concrete themes over greetings, filler, ASR garbage.",
            "A quote is evidence a phrase was uttered, NOT evidence it is factually true.",
            "Never infer speaker identity.",
            "If window has no clear substantive topic, return an empty topics array."
        ],
        "window_index": window["window_index"],
        "cues": [{"source_index": c["source_index"], "text": c["text"]}
                 for c in cues],
    }
    raw = chat([
        {"role": "system", "content": "Український редактор стенограм. Лише JSON з точними цитатами."},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ])
    try:
        result = json.loads(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("INVALID_WINDOW_TOPIC_JSON") from None
    proposals = result.get("topics") if isinstance(result, dict) else None
    if not isinstance(proposals, list) or len(proposals) > 3:
        raise ValueError("INVALID_WINDOW_TOPIC_COUNT")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in proposals:
        if not isinstance(item, dict):
            rejected.append({"reason": "INVALID_PROPOSAL"})
            continue
        index = item.get("source_index")
        quote = item.get("quote")
        label = _normalized(item.get("label_uk"))
        kind = item.get("kind")
        # The source index is the authority; a model's quotation is NOT.
        # Minor punctuation/ASR formatting drift can be normalized, but
        # substantially different or invented speech is always rejected.
        exact = (type(index) is int and index in source_by_id
                 and isinstance(quote, str)
                 and _normalized(quote) == source_by_id[index]["text"])
        close = (not exact and type(index) is int and index in source_by_id
                 and isinstance(quote, str) and len(_normalized(quote)) >= 28
                 and SequenceMatcher(None, _normalized(quote).casefold(),
                                     source_by_id[index]["text"].casefold()).ratio() >= 0.94)
        if (type(index) is not int or index not in source_by_id
                or index in seen or not (exact or close)
                or not 5 <= len(label) <= 120
                or kind not in {"question", "opinion", "report", "speech"}):
            rejected.append({"reason": "UNSUPPORTED_WINDOW_TOPIC",
                             "source_index": index if type(index) is int else None})
            continue
        seen.add(index)
        cue = source_by_id[index]
        accepted.append({
            "window_index": window["window_index"],
            "source_index": index,
            "start_s": cue["start_s"],
            "source_quote": cue["text"],
            "source_quote_restored_from_original": bool(close),
            "topic_candidate_not_fact": label,
            "statement_kind_candidate": kind,
            "speaker_verified": False,
            "factual_truth_verified": False,
            "editorial_verified": False,
        })
    return {"window_index": window["window_index"],
            "source_sha256": window["source_sha256"],
            "cue_count": window["cue_count"],
            "topics": accepted, "rejected": rejected,
            "needs_review": True, "publication_allowed": False}



def retry_empty_window_by_index(
    window: dict[str, Any], *, chat: Chat,
) -> dict[str, Any]:
    """One conservative retry: model selects source IDs, NOT quotation text.

    Exact source text is always recovered from the original caption cue.
    Absence of a substantive theme remains an explicit review blocker.
    """
    cues = window.get("cues") or []
    if not cues:
        raise ValueError("EMPTY_SOURCE_WINDOW")
    by_id = {cue["source_index"]: cue for cue in cues}
    prompt = {
        "task": "Find up to TWO substantive subjects in this one SRT window. Return source indices only, never copy source text.",
        "required_json": {"topics": [
            {"source_index": "integer from supplied cues",
             "label_uk": "concrete short Ukrainian topic; not an external fact",
             "kind": "question|opinion|report|speech"}]},
        "rules": [
            "Return only source_index IDs from the original list. NEVER invent IDs.",
            "Do not infer news facts, outcomes, speaker identity or policies.",
            "A spoken claim is not proof that it is true.",
            "If the dialogue is only greetings or noise, return topics: []."
        ],
        "window_index": window["window_index"],
        "cues": [{"source_index": cue["source_index"], "text": cue["text"]}
                 for cue in cues],
    }
    raw = chat([
        {"role": "system", "content": "Редактор українських стенограм. Повертай лише JSON. Точні цитати бери тільки з джерела."},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ])
    try:
        response = json.loads(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("INVALID_SOURCE_INDEX_RETRY_JSON") from None
    proposals = response.get("topics") if isinstance(response, dict) else None
    if not isinstance(proposals, list) or len(proposals) > 2:
        raise ValueError("INVALID_SOURCE_INDEX_RETRY_COUNT")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in proposals:
        if not isinstance(item, dict):
            rejected.append({"reason": "INVALID_INDEX_TOPIC"})
            continue
        index = item.get("source_index")
        label = _normalized(item.get("label_uk"))
        kind = item.get("kind")
        if (type(index) is not int or index not in by_id or index in seen
                or not 5 <= len(label) <= 120
                or kind not in {"question", "opinion", "report", "speech"}):
            rejected.append({"reason": "INVALID_INDEX_TOPIC"})
            continue
        seen.add(index)
        cue = by_id[index]
        accepted.append({
            "window_index": window["window_index"],
            "source_index": index,
            "start_s": cue["start_s"],
            "source_quote": cue["text"],
            "source_quote_restored_from_original": True,
            "topic_candidate_not_fact": label,
            "statement_kind_candidate": kind,
            "speaker_verified": False,
            "factual_truth_verified": False,
            "editorial_verified": False,
            "retry_index_only": True,
        })
    return {"window_index": window["window_index"],
            "source_sha256": window["source_sha256"],
            "cue_count": window["cue_count"],
            "topics": accepted, "rejected": rejected,
            "needs_review": True, "publication_allowed": False}



def analyze_full_original_transcript(
    rows: list[dict[str, Any]], *, chat: Chat, max_chars: int = 3200,
) -> dict[str, Any]:
    """Cover every substantive SRT row before SEO composition."""
    windows = split_transcript_windows(rows, max_chars=max_chars)
    reports = [extract_grounded_window_topics(window, chat=chat)
               for window in windows]
    # A rejected copy of an otherwise meaningful cue should not erase its
    # original SRT window. One bounded index-only retry preserves provenance.
    retried_windows: list[int] = []
    for i, (window, report) in enumerate(zip(windows, reports)):
        if report["topics"]:
            continue
        retried_windows.append(i)
        recovered = retry_empty_window_by_index(window, chat=chat)
        reports[i] = {
            **recovered,
            "rejected": report["rejected"] + recovered["rejected"],
            "first_pass_empty": True,
        }
    expected = [cue["source_index"] for window in windows
                for cue in window["cues"]]
    included = [index for window in windows for index in
                (cue["source_index"] for cue in window["cues"])]
    if expected != included or len(set(included)) != len(included):
        raise ValueError("ORIGINAL_TRANSCRIPT_COVERAGE_MISMATCH")
    records = [topic for r in reports for topic in r["topics"]]
    missing_topic_windows = [r["window_index"] for r in reports if not r["topics"]]
    return {"schema": "RG_FULL_SRT_TOPIC_MAP_V1",
            "window_count": len(windows), "source_cues_processed": len(expected),
            "all_nonempty_cues_covered": True,
            "windows": [{"index": w["window_index"], "start_s": w["start_s"],
                         "end_s": w["end_s"], "source_sha256": w["source_sha256"],
                         "topics_count": len(r["topics"])}
                        for w, r in zip(windows, reports)],
            "topic_records_review_only": records,
            "rejected_topic_proposals": sum(len(r["rejected"]) for r in reports),
            "windows_without_substantive_topics": missing_topic_windows,
            "windows_with_index_only_retry": retried_windows,
            "needs_review": True, "publication_allowed": False}
