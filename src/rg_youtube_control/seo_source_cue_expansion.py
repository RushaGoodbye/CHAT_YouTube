"""Expand SEO source evidence from exact timestamped SRT cues.

Candidates are NOT verified facts or approved SEO. The downstream editorial
critic must check every paraphrase and its attribution independently.
"""
from __future__ import annotations
import math
import re
from typing import Any, Iterable

_WORD = re.compile(r"[\w]+", re.UNICODE)
_QUESTION = re.compile(r"[?？]|\b(?:почему|зачем|сколько|какой|какая|какие|чому|навіщо|скільки|який|яка|які)\b", re.I)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _tokens(value: str) -> set[str]:
    return {w[:8] for w in _WORD.findall(value.casefold()) if len(w) >= 4}


def _stamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def expand_source_cue_candidates(
    transcript_rows: Iterable[dict[str, Any]],
    timeline_report: dict[str, Any],
    *,
    limit: int = 16,
    per_window: int = 4,
    min_chars: int = 28,
    max_chars: int = 220,
    include_unverified_for_review: bool = False,
) -> dict[str, Any]:
    """Choose exact source cues evenly across verified timeline windows.

    Never assemble a synthetic quotation across overlapping ASR cues, infer
    the speaker, or upgrade an attributed claim to independently true.
    """
    if not 1 <= limit <= 100 or not 1 <= per_window <= 15:
        raise ValueError("INVALID_EVIDENCE_SELECTION_LIMIT")
    if not 8 <= min_chars <= max_chars <= 5000:
        raise ValueError("INVALID_SOURCE_CUE_BOUNDS")
    blocks = timeline_report.get("blocks") if isinstance(timeline_report, dict) else None
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("MISSING_TIMELINE_BLOCKS")
    all_rows = list(transcript_rows)
    source = []
    for ix, row in enumerate(all_rows):
        if not isinstance(row, dict):
            continue
        quote = _clean(row.get("text"))
        try:
            start = float(row.get("start"))
            duration = float(row.get("duration") or 0)
        except (ValueError, TypeError):
            continue
        if not (math.isfinite(start) and math.isfinite(duration)
                and start >= 0 and duration >= 0 and min_chars <= len(quote) <= max_chars):
            continue
        tokens = _tokens(quote)
        if len(tokens) < 4:
            continue
        source.append((ix, start, duration, quote, tokens))

    window_groups: list[tuple[int, list[dict[str, Any]]]] = []
    unverified: list[int] = []
    seen_block_ids: set[int] = set()
    invalid_block_count = 0
    for b in blocks:
        if not isinstance(b, dict):
            invalid_block_count += 1
            continue
        try:
            index = int(b["index"])
            begin = float(b["start"])
            end = float(b["end"])
        except (KeyError, ValueError, TypeError):
            invalid_block_count += 1
            continue
        if (index in seen_block_ids or not math.isfinite(begin)
            or not math.isfinite(end) or begin < 0 or end < begin):
            invalid_block_count += 1
            continue
        seen_block_ids.add(index)
        is_verified = b.get("verified") is True
        if not is_verified:
            unverified.append(index)
            if not include_unverified_for_review:
                continue
        eligible = []
        for row_index, start, duration, quote, tokens in source:
            if not begin <= start <= end:
                continue
            score = len(tokens) + min(len(quote), 140) / 40
            if quote[-1:] in (".", "!", "?"):
                score += 3
            if _QUESTION.search(quote):
                score += 1
            eligible.append((score, row_index, start, duration, quote, tokens))
        eligible.sort(key=lambda x: (-x[0], x[2], x[1]))
        candidates = []
        local_signatures: list[set[str]] = []
        for score, row_index, start, duration, quote, tokens in eligible:
            if any(len(tokens & prior) / max(1, len(tokens | prior)) >= 0.72
                   for prior in local_signatures):
                continue
            local_signatures.append(tokens)
            # Adjacent captions supply *context*, not a synthetic quotation or
            # proof of continuous speaker identity. Keep each raw cue exact.
            context_parts = []
            for neighbor_index in (row_index - 1, row_index, row_index + 1):
                if not 0 <= neighbor_index < len(all_rows):
                    continue
                neighbor = all_rows[neighbor_index]
                if not isinstance(neighbor, dict):
                    continue
                try:
                    neighbor_start = float(neighbor.get("start"))
                except (TypeError, ValueError):
                    continue
                neighbor_text = _clean(neighbor.get("text"))
                if (math.isfinite(neighbor_start) and begin <= neighbor_start <= end
                        and abs(neighbor_start - start) <= 8
                        and 0 < len(neighbor_text) <= 220):
                    context_parts.append(neighbor_text)
            context_window = _clean(" ".join(context_parts))
            if quote not in context_window:
                context_window = quote
            candidates.append({
                "source_id": f"cue_{row_index + 1}",
                "block_index": index,
                "start_s": start,
                "end_s": start + duration,
                "timestamp": _stamp(start),
                "source_quote": quote,
                "source_precision": "single_original_cue",
                "context_window": context_window[:700],
                "context_is_not_speaker_proof": True,
                # Unverified timeline windows are allowed only as literal
                # draft evidence, NEVER as validated topics or semantic PASS.
                "model_block_verified": is_verified,
                # Most ASR cues are fragments. Never imply that a cue lacking
                # terminal punctuation is a complete assertion.
                "may_be_incomplete": quote[-1:] not in (".", "!", "?"),
                "is_possible_question": bool(_QUESTION.search(quote)),
                "speaker_identified": False,
                "factual_truth_verified": False,
                "editorial_approved": False,
            })
            if len(candidates) >= per_window:
                break
        window_groups.append((index, candidates))

    selected: list[dict[str, Any]] = []
    overall_signatures: list[set[str]] = []
    for slot in range(per_window):
        for _, candidates in window_groups:
            if slot >= len(candidates):
                continue
            item = candidates[slot]
            tokens = _tokens(item["source_quote"])
            if any(len(tokens & prev) / max(1, len(tokens | prev)) >= 0.72
                   for prev in overall_signatures):
                continue
            selected.append(item)
            overall_signatures.append(tokens)
            if len(selected) == limit:
                break
        if len(selected) == limit:
            break

    return {
        "schema": "RG_SOURCE_CUE_EXPANSION_V1",
        "evidence_candidates": selected,
        "candidate_count": len(selected),
        "verified_windows_with_candidates": sum(bool(items) for _, items in window_groups),
        "candidate_windows": sorted({x["block_index"] for x in selected}),
        "unverified_candidate_ids": [
            x["source_id"] for x in selected if not x["model_block_verified"]
        ],
        "enough_diverse_candidates": (len(selected) >= 3 and
            len({x["block_index"] for x in selected}) >= 2),
        "unverified_block_ids": sorted(unverified),
        "invalid_block_count": invalid_block_count,
        "complete_timeline_verified": (bool(window_groups) and
            not unverified and invalid_block_count == 0),
        "needs_independent_semantic_review": True,
        "publication_allowed": False,
        "human_approved": False,
    }
