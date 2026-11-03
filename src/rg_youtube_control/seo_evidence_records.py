"""G2: source-anchored evidence records for the universal SEO analysis.

Only verbatim quotes establish that something was spoken, not that it is true.
Never convert an attributed statement into an independently verified fact.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


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
            candidates = []
            for row in rows:
                row_text = _clean(row.get("text"))
                if quote.casefold() in row_text.casefold():
                    candidates.append(row)
            if candidates:
                source = min(candidates, key=lambda row: float(row.get("start") or 0))
                start = float(source.get("start") or 0)
                duration = float(source.get("duration") or 0)
                precision = "caption"
            elif quote.casefold() in block_text.casefold() and block.get("start") is not None:
                start = float(block["start"])
                duration = max(0.0, float(block.get("end", start)) - start)
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
                "statement_kind": "question" if "?" in quote or "？" in quote else "attributed_speech",
                "factual_truth_verified": False,
            })
    covered = int(timeline_report.get("blocks_analyzed") or 0)
    verified = int(timeline_report.get("blocks_with_evidence") or 0)
    return {
        "schema": "RG_UNIVERSAL_EVIDENCE_V1",
        "video_id": video_id,
        "blocks_analyzed": covered,
        "blocks_with_evidence": verified,
        "evidence_records": records,
        "rejected_evidence": rejected,
        "needs_review": True,
        "publication_allowed": False,
    }
