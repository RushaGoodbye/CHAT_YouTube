"""G2: source-anchored evidence records for the universal SEO analysis.

Only verbatim quotes establish that something was spoken, not that it is true.
Never convert an attributed statement into an independently verified fact.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def classify_attributed_statement(quote: str) -> str:
    """Conservative labels, not an LLM judgment or independent fact check."""
    text = _clean(quote).casefold()
    if "?" in text or "？" in text:
        return "question"
    # Require a syntactic speech marker; otherwise stay unclassified.
    if re.search(r"(?<!\w)(?:кажется|здається|думаю|считаю|вважаю|по-моему|на мою думку|я думаю|мне кажется)(?!\w)", text):
        return "opinion"
    if re.search(r"(?<!\w)(?:говорят|кажуть|нібито|якобы|по слухам|за чутками)(?!\w)", text):
        return "allegation"
    return "attributed_speech"


def build_evidence_records(
    *, video_id: str, timeline_report: dict[str, Any],
    transcript_rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Convert a whole-transcript report into reviewable, timestamped evidence.

    A quote must occur in an actual caption row or as a contiguous string
    within the supplied verified timeline block. Block-level citations explicitly
    preserve uncertainty when the quote spans caption rows.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("INVALID_VIDEO_ID")
    rows = list(transcript_rows)
    if not rows or not isinstance(timeline_report, dict):
        raise ValueError("MISSING_EVIDENCE_INPUT")
    records: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for block in timeline_report.get("blocks") or []:
        if not isinstance(block, dict) or not block.get("verified"):
            continue
        block_text = _clean(block.get("text", ""))
        for item in block.get("topics") or []:
            if not isinstance(item, dict):
                continue
            quote = _clean(item.get("evidence"))
            topic = _clean(item.get("topic"))
            summary = _clean(item.get("summary_uk"))
            if not (8 <= len(quote) <= 240 and topic and summary):
                rejected.append({"block": block.get("index"), "reason": "INCOMPLETE_EVIDENCE"})
                continue
            if block.get("start") is None or block.get("end") is None:
                rejected.append({"block": block.get("index"), "reason": "MISSING_BLOCK_WINDOW"})
                continue
            block_start, block_end = float(block["start"]), float(block["end"])
            if block_start < 0 or block_end < block_start:
                rejected.append({"block": block.get("index"), "reason": "INVALID_BLOCK_WINDOW"})
                continue
            candidates = []
            for row in rows:
                row_start = float(row.get("start") or 0)
                row_text = _clean(row.get("text"))
                if block_start <= row_start <= block_end and quote.casefold() in row_text.casefold():
                    candidates.append(row)
            if candidates:
                source = min(candidates, key=lambda row: float(row.get("start") or 0))
                start = float(source.get("start") or 0)
                duration = float(source.get("duration") or 0)
                precision = "caption"
            elif block.get("start") is not None and block.get("end") is not None:
                start = float(block["start"])
                end = float(block["end"])
                # Quotations sometimes span adjacent subtitle cues. Reconstruct
                # only this block's original captions, never the whole video.
                window = _clean(" ".join(
                    str(row.get("text") or "") for row in rows
                    if start <= float(row.get("start") or 0) <= end
                ))
                # Never trust model-authored block text as source evidence:
                # only the original timestamped caption rows establish quotes.
                if quote.casefold() not in window.casefold():
                    rejected.append({"block": block.get("index"), "reason": "QUOTE_NOT_IN_SOURCE"})
                    continue
                duration = max(0.0, end - start)
                precision = "timeline_block"
            else:
                rejected.append({"block": block.get("index"), "reason": "QUOTE_NOT_IN_SOURCE"})
                continue
            if start < 0 or duration < 0:
                rejected.append({"block": block.get("index"), "reason": "INVALID_EVIDENCE_TIMESTAMP"})
                continue
            records.append({
                "video_id": video_id,
                "block_index": block.get("index"),
                "topic": topic,
                "model_summary_not_fact": summary,
                "verbatim_quote": quote,
                "start_s": start,
                "end_s": start + duration,
                "timestamp_precision": precision,
                "statement_kind": classify_attributed_statement(quote),
                "factual_truth_verified": False,
            })
    covered = int(timeline_report.get("blocks_analyzed") or 0)
    verified = int(timeline_report.get("blocks_with_evidence") or 0)
    # A model may mark a block as 'verified' even though no quotation survives
    # the original-caption check. Preserve the missing block IDs explicitly.
    expected_ids = {
        b.get("index") for b in (timeline_report.get("blocks") or [])
        if isinstance(b, dict) and b.get("index") is not None
    }
    grounded_ids = {r["block_index"] for r in records}
    missing_ids = sorted(expected_ids - grounded_ids, key=str)
    return {
        "schema": "RG_UNIVERSAL_EVIDENCE_V1",
        "video_id": video_id,
        "blocks_analyzed": covered,
        "blocks_with_evidence": verified,
        "evidence_records": records,
        "rejected_evidence": rejected,
        "blocks_without_grounded_quotes": missing_ids,
        "complete_evidence_coverage": bool(expected_ids) and not missing_ids,
        "needs_review": True,
        "publication_allowed": False,
    }


def grounded_evidence_outline(source_records: dict[str, Any]) -> str:
    """Only vetted source quotes may enter SEO model context.

    Model-derived topic labels are suggestions, not independent facts.
    Unvetted original model claims and failed quotations are deliberately
    excluded from this context.
    """
    items = source_records.get("evidence_records") or []
    if not items or source_records.get("blocks_without_grounded_quotes"):
        raise ValueError("INCOMPLETE_GROUNDED_EVIDENCE")
    lines = [
        "Це лише репліки учасників відео, а не перевірені факти. "
        "Не перетворюй твердження, припущення чи запитання на доведені події."
    ]
    for rec in items:
        lines.append(
            f"[{int(float(rec['start_s']) // 60):02d}:"
            f"{int(float(rec['start_s']) % 60):02d}] "
            f"Тема-кандидат: {rec['topic']} "
            f"| Тип: {rec['statement_kind']} "
            f"| Дослівна репліка: «{rec['verbatim_quote']}»"
        )
    return "\n".join(lines)
