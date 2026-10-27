"""Balanced, source-grounded excerpts for long video transcripts.

The SEO model must not see only the first 9-24k characters of a 3-hour
transcript. Choose windows from across the video, including highly relevant
late windows tied to the CURRENT YouTube headline. No LLM or network calls.
"""
from __future__ import annotations

import re

_GENERIC = frozenset({
    "раша", "гудбай", "россия", "россии", "россию", "россий", "россиян",
    "русские", "русский", "россияне", "чат", "рулетка", "ютуб",
    "youtube", "канал", "стрим", "стрима", "сегодня", "сейчас",
    "новости", "ситуация", "разговор", "диалог", "обсуждение",
    "происходит", "правда", "война", "войны", "войну",
    "видео", "снова", "почему", "после", "этого", "который",
})


def _topic_stems(title: str) -> set[str]:
    words = re.findall(r"[a-zа-яёіїєґ]{5,}", title.casefold())
    return {word[:5] for word in words if word not in _GENERIC
            and word[:5] not in {"росси", "русск", "ютуб", "война"}}


def select_source_excerpt(
    title: str,
    transcript: str,
    *,
    char_budget: int = 23000,
    window_chars: int = 1000,
) -> str:
    """Select representative and topic-relevant source windows, in time order.

    A bounded amount is selected from the start, middle, and end regardless
    of what the current title says. Matching title terms preferentially
    allocate the rest of the budget. The source is never paraphrased.
    """
    source = " ".join(str(transcript or "").split())
    if len(source) <= char_budget:
        return source
    if char_budget < 800 or window_chars < 100:
        raise ValueError("Excerpt budget too small")
    # Use nonoverlapping windows so the budget goes to diverse footage.
    windows = [source[i:i + window_chars] for i in range(0, len(source), window_chars)]
    n = len(windows)
    capacity = max(1, char_budget // (window_chars + 2))
    anchors = _topic_stems(title)
    # Always sample across the video, including later segments.
    representative = [0, n // 2, n - 1, n // 4, (3 * n) // 4]
    # Reserve at least one slot for title-grounded evidence. On small
    # budgets, five fixed samples previously consumed the whole budget,
    # silently discarding the central news subject.
    representative_slots = max(0, capacity - 1)
    selected = set(representative[:min(len(representative),
                                       representative_slots)])
    # Select title-subject matches from the ENTIRE transcript, not only intro.
    scored = []
    for index, excerpt in enumerate(windows):
        text = excerpt.casefold()
        score = sum(min(4, len(re.findall(r"(?<!\w)" + re.escape(stem),
                                    text))) for stem in anchors)
        if score:
            scored.append((score, index))
    # Prioritize the headline topic but preserve chronological excerpts.
    for _, index in sorted(scored, key=lambda pair: (-pair[0], pair[1])):
        if len(selected) >= capacity:
            break
        selected.add(index)
    # No exact lexical title match? Fill the remaining context evenly.
    if len(selected) < capacity:
        for step in range(capacity):
            index = min(n - 1, int((step + 0.5) * n / capacity))
            selected.add(index)
            if len(selected) >= capacity:
                break
    chosen = sorted(selected)[:capacity]
    # Distinct windows are separated without injecting invented claims.
    return "\n[…]\n".join(windows[index].strip() for index in chosen)[:char_budget]
