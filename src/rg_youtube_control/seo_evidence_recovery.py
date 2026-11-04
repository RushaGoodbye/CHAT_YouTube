"""G2 bounded recovery for blocks whose model quotations failed source validation.

The source, never an LLM, chooses the exact quotation. The model may ONLY
suggest an attributed topic and a summary; neither is a proven external fact.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .seo_evidence_records import build_evidence_records


def recover_missing_source_blocks(
    *,
    video_id: str,
    timeline_report: dict[str, Any],
    transcript_rows: list[dict[str, Any]],
    chat: Callable[..., str],
    model: str,
    timeout: float = 90.0,
    max_attempts: int = 1,
) -> dict[str, Any]:
    """Recover missing block coverage with at most one new LM call per block.

    Never repair a model quote by guessing. A literal caption is pinned into
    the final record and is still checked against the original captions.
    """
    if not (1 <= max_attempts <= 3):
        raise ValueError("INVALID_RECOVERY_ATTEMPTS")
    report = build_evidence_records(
        video_id=video_id, timeline_report=timeline_report,
        transcript_rows=transcript_rows,
    )
    initial_missing = list(report["blocks_without_grounded_quotes"])
    attempts = 0
    recovered: list[Any] = []
    failed: list[Any] = []
    for block in timeline_report.get("blocks") or []:
        index = block.get("index")
        if index not in initial_missing:
            continue
        start, end = float(block.get("start", -1)), float(block.get("end", -1))
        candidates = []
        for row in transcript_rows:
            row_time = float(row.get("start", -1))
            quote = " ".join(str(row.get("text") or "").split())
            if (start <= row_time <= end and 28 <= len(quote) <= 220
                    and len(re.findall(r"\w+", quote)) >= 6):
                candidates.append(quote)
        if not candidates:
            failed.append({"block_index": index, "reason": "NO_USABLE_SOURCE_QUOTE"})
            continue
        # Prefer a caption with varied words over repeated filler. Never
        # synthesize a quotation from text the model generated.
        ranked = sorted(set(candidates), key=lambda x: (
            len(set(re.findall(r"\w+", x.casefold()))), len(x),
        ), reverse=True)
        accepted = False
        for attempt in range(min(max_attempts, len(ranked))):
            quote = ranked[attempt]
            attempts += 1
            prompt = (
                "Поверни тільки JSON-об'єкт із полями topic і summary_uk. "
                "Визнач коротку тему та опис українською ТІЛЬКИ за однією "
                "дослівною реплікою. Це висловлювання людини, НЕ доведений факт. "
                "Не вигадуй імен, чисел, посад, мотивів чи подій. "
                "Якщо зміст незрозумілий, поверни порожні рядки.\n"
                + quote
            )
            try:
                raw = chat(
                    [{"role": "system", "content": "Тільки JSON. Не додавай фактів."},
                     {"role": "user", "content": prompt}],
                    model=model, timeout=timeout, temperature=0.0, json_mode=True,
                )
                payload = json.loads(str(raw).strip())
                if not isinstance(payload, dict):
                    raise ValueError("INVALID_MODEL_OUTPUT")
                topic = " ".join(str(payload.get("topic") or "").split())
                summary = " ".join(str(payload.get("summary_uk") or "").split())
                if not (5 <= len(topic) <= 110 and 15 <= len(summary) <= 350):
                    continue
                original_topics = list(block.get("topics") or [])
                block["topics"] = original_topics + [{
                    "topic": topic, "summary_uk": summary, "evidence": quote,
                    "recovered_from_source_caption": True,
                    "editorial_review_required": True,
                }]
                block["verified"] = True
                accepted = True
                recovered.append(index)
                break
            except (ValueError, TypeError, KeyError, TimeoutError, RuntimeError, OSError):
                continue
        if not accepted:
            failed.append({"block_index": index, "reason": "MODEL_RECOVERY_FAILED"})
    outcome = build_evidence_records(
        video_id=video_id, timeline_report=timeline_report,
        transcript_rows=transcript_rows,
    )
    outcome["recovery"] = {
        "initial_missing": initial_missing,
        "recovered_blocks": recovered,
        "unrecovered": failed,
        "model_calls": attempts,
        "recovery_requires_editorial_review": bool(recovered),
    }
    return outcome
