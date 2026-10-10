"""Bounded evidence context for long videos.

Never silently pass an oversized transcript outline into Ollama, where it may
be truncated. Keep the original full timeline report on disk; mark every
shortened/missing detail for human review.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from .dialogue_seo import evidence_outline_text


@dataclass(frozen=True)
class EvidenceContext:
    text: str
    topic_total: int
    topic_included: int
    topics_omitted: tuple[str, ...]
    compacted: bool
    detail_shortened: bool


def _coverage_order(count: int) -> list[int]:
    """Choose endpoints and middle recursively if not all topic labels fit."""
    if count <= 0:
        return []
    result = [0]
    if count > 1:
        result.append(count - 1)
    ranges = deque([(0, count - 1)])
    while ranges:
        start, end = ranges.popleft()
        if end - start <= 1:
            continue
        middle = (start + end) // 2
        if middle not in result:
            result.append(middle)
        ranges.append((start, middle))
        ranges.append((middle, end))
    return result


def bounded_evidence_context(
    report: dict[str, Any], *, max_chars: int = 26000,
) -> EvidenceContext:
    """Prefer ALL chronological topic labels; enrich with quotes if space.

    If even compact topic labels will not fit, sample across the entire
    timeline and explicitly report omitted topics. This is NOT proof of
    a semantically complete summary.
    """
    if max_chars < 500:
        raise ValueError("max_chars must be >= 500")
    blocks = report.get("blocks") or []
    topics = [
        (
            str(block.get("start_stamp") or ""),
            str(item.get("topic") or "").strip(),
            str(item.get("summary_uk") or "").strip(),
            str(item.get("evidence") or "").strip(),
        )
        for block in blocks if isinstance(block, dict)
        for item in (block.get("topics") or []) if isinstance(item, dict)
        if str(item.get("topic") or "").strip()
    ]
    full = evidence_outline_text(report)
    if len(full) <= max_chars:
        return EvidenceContext(full, len(topics), len(topics), (), False, False)
    if not topics:
        return EvidenceContext(
            full[:max_chars], 0, 0, (), True, True,
        )

    # Leave room for a warning in the final prompt.
    reserved = 180
    limit = max_chars - reserved
    labels = [f"[{stamp}] ТЕМА: {topic}" for stamp, topic, _, _ in topics]
    required = sum(len(label) + 1 for label in labels)
    selected: set[int] = set()
    used = 0
    if required <= limit:
        selected.update(range(len(labels)))
        used = required
    else:
        for index in _coverage_order(len(labels)):
            cost = len(labels[index]) + 1
            if used + cost <= limit:
                selected.add(index)
                used += cost

    # Spread evidence fairly across the whole video; never truncate a quote
    # in the middle of a word and label it as a verified literal citation.
    suffixes: dict[int, str] = {}
    for index in sorted(selected):
        evidence = topics[index][3]
        addon = f" | ЦИТАТА: {evidence}" if evidence else ""
        if addon and used + len(addon) <= limit:
            suffixes[index] = addon
            used += len(addon)
    for index in sorted(selected):
        summary = topics[index][2]
        addon = f" | ТЕЗА: {summary}" if summary else ""
        if addon and used + len(addon) <= limit:
            suffixes[index] = suffixes.get(index, "") + addon
            used += len(addon)

    omitted = tuple(
        f"[{topics[index][0]}] {topics[index][1]}"
        for index in range(len(topics)) if index not in selected
    )
    header = (
        f"УВАГА: контекст стислий; повний звіт збережено окремо. "
        f"Тем у джерелі: {len(topics)}; у запиті: {len(selected)}; "
        f"поза запитом: {len(omitted)}. Не стверджуй, що всі теми перевірені.\n"
    )
    lines = [labels[index] + suffixes.get(index, "") for index in sorted(selected)]
    combined = header + "\n".join(lines)
    if len(combined) > max_chars:
        raise ValueError("Internal evidence context budget exceeded")
    return EvidenceContext(
        combined, len(topics), len(selected), omitted, True, True,
    )
