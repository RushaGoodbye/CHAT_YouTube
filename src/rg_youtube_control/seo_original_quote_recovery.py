"""Repair omitted named-subject evidence using VERBATIM original transcript text.

A model might miss a named anchor in otherwise valid text. Never use the
video title itself as a source quotation. Insert only validated excerpts from
the exact original transcript block and require editorial review. This module
never edits source files, publishes videos, or invents timestamps.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Iterable

from .dialogue_seo import _validate_topics, split_timeline
from .seo_source_alignment import (
    _named_anchors, check_title_against_transcript,
)

_WORD_RE = re.compile(r"[\wіїєґё]+", re.UNICODE)


def _context_quote(
    text: str, aliases: tuple[str, ...], current_title: str,
) -> str:
    """Extract a whole-word bounded 8–240 char literal around named subject."""
    for match in _WORD_RE.finditer(text):
        word = match.group().casefold()
        if not any(word == alias or word.startswith(alias) for alias in aliases):
            continue
        start = max(0, match.start() - 65)
        end = min(len(text), match.end() + 90)
        if start and not text[start - 1].isspace():
            next_space = next(
                (i for i in range(start, match.start()) if text[i].isspace()),
                None,
            )
            if next_space is not None:
                start = next_space + 1
        if end < len(text) and not text[end].isspace():
            previous_space = text.rfind(" ", match.end(), end)
            if previous_space > match.end():
                end = previous_space
        quote = " ".join(text[start:end].split())
        if 8 <= len(quote) <= 240 and _supports_title_event_in_quote(
            current_title, quote,
        ):
            return quote
    return ""


def _supports_title_event_in_quote(title: str, quote: str) -> bool:
    """Avoid promoting a one-off name drop into a headline about a major event."""
    title_words = title.casefold()
    quote_words = quote.casefold()
    event_families = (
        (
            ("уволь", "звільнен", "звильнен", "відстав", "отстав"),
            ("увол", "звільн", "звильн", "отстав", "відстав",
             "снят с пост", "сменил должност", "поменял должност"),
        ),
        (
            ("корруп", "коруп"),
            ("корруп", "коруп", "взят", "хабар"),
        ),
    )
    required = [
        options for triggers, options in event_families
        if any(trigger in title_words for trigger in triggers)
    ]
    return not required or any(
        fragment in quote_words for options in required for fragment in options
    )


def recover_omitted_named_quotes(
    evidence_report: dict[str, Any],
    transcript_rows: Iterable[dict[str, Any]],
    current_title: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Add strictly validated original-text quotes for missed title anchors.

    The model-selected evidence is never rewritten. A new additional topic is
    visibly marked as original-transcript recovery, not a model verification.
    Returns (new_report, recovered_anchors). If original text is insufficient
    or segmentation differs, the calling hard gate must still reject.
    """
    report = copy.deepcopy(evidence_report)
    quotations = " ".join(
        str(topic.get("evidence") or "")
        for block in report.get("blocks") or []
        if block.get("verified") is not False
        for topic in block.get("topics") or []
        if isinstance(topic, dict)
    )
    missing = check_title_against_transcript(current_title, quotations).missing
    if not missing:
        return report, ()

    source_blocks = split_timeline(transcript_rows)
    output_blocks = report.get("blocks") or []
    if len(source_blocks) != len(output_blocks):
        return report, ()
    for left, right in zip(source_blocks, output_blocks):
        if left["index"] != right.get("index"):
            return report, ()

    recovered: list[str] = []
    proof: list[dict[str, Any]] = []
    for label, aliases in _named_anchors(current_title):
        if label not in missing:
            continue
        for source_block, output_block in zip(source_blocks, output_blocks):
            quote = _context_quote(
                source_block["text"], aliases, current_title,
            )
            if not quote:
                continue
            summary = (
                f"У фрагменті співрозмовники згадують {label}. "
                "Цитату знайдено дослівно в оригінальній розшифровці, "
                "але редактор має перевірити її контекст."
            )
            verified = _validate_topics(
                {
                    "topics": [{
                        "topic": f"Згадка імені {label}",
                        "summary_uk": summary,
                        "evidence": quote,
                    }],
                },
                source_block,
            )
            if not verified["verified"]:
                continue
            topic = verified["topics"][0]
            topic["origin"] = "verbatim-original-transcript-recovery"
            output_block.setdefault("topics", []).append(topic)
            output_block["verified"] = True
            output_block["excerpt"] = ""
            recovered.append(label)
            proof.append({
                "anchor": label,
                "block_index": source_block["index"],
                "quote": quote,
                "origin": "verbatim-original-transcript-recovery",
            })
            break

    if recovered:
        report["source_anchor_recovery"] = proof
        report["needs_review"] = True
        report["unverified_blocks"] = [
            block.get("index") for block in output_blocks
            if block.get("verified") is False
        ]
        report["blocks_with_evidence"] = sum(
            bool(block.get("verified")) for block in output_blocks
        )
    return report, tuple(recovered)
