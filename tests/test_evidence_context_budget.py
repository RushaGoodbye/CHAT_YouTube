"""Evidence-context constraints for long archival streams (offline; no model quota)."""
from __future__ import annotations

import ast
from pathlib import Path

from rg_youtube_control.evidence_context import (
    _coverage_order, bounded_evidence_context,
)


def _report(block_count=180, topics_per_block=3):
    blocks = []
    for index in range(block_count):
        h, minutes = divmod(index * 5, 60)
        stamp = f"{h:02d}:{minutes:02d}:00"
        topics = []
        for number in range(topics_per_block):
            topics.append({
                "topic": f"Розмова {index:03d} про ситуацію номер {number} і реальні ціни на пальне",
                "summary_uk": f"Співрозмовник у частині {index} розповів про місцеві проблеми. " * 3,
                "evidence": f"Я говорю про фрагмент {index} та місцеві проблеми і про ціни на пальне",
            })
        blocks.append({"start_stamp": stamp, "topics": topics})
    return {"blocks": blocks}


def test_short_evidence_is_kept_verbatim_without_degradation():
    report = _report(2, 1)
    result = bounded_evidence_context(report)
    assert result.topic_total == 2
    assert result.topic_included == 2
    assert result.topics_omitted == ()
    assert not result.compacted
    assert not result.detail_shortened
    assert "ЦИТАТА:" in result.text
    assert "ТЕЗА:" in result.text


def test_15_hour_stream_has_bounded_prompt_and_chronological_topic_presence():
    report = _report(180, 3)
    result = bounded_evidence_context(report, max_chars=26000)
    assert len(result.text) <= 26000
    assert result.topic_total == 540
    assert result.compacted
    assert result.detail_shortened
    assert result.topic_included + len(result.topics_omitted) == result.topic_total
    # The first and last timeline blocks are never lost to front-truncation.
    assert "[00:00:00]" in result.text
    assert "[14:55:00]" in result.text
    assert "контекст стислий" in result.text
    assert "Не стверджуй" in result.text


def test_oversize_outline_samples_early_middle_and_late_blocks_instead_of_prefix():
    report = _report(120, 3)
    result = bounded_evidence_context(report, max_chars=2600)
    assert result.topic_total == 360
    assert result.topic_included < result.topic_total
    assert len(result.text) <= 2600
    assert result.topics_omitted
    # Keep both ends and middle when no small prompt can fit all topics.
    assert "[00:00:00]" in result.text
    assert "[09:55:00]" in result.text
    assert "[04:55:00]" in result.text or "[05:00:00]" in result.text


def test_compressed_outline_keeps_all_topic_labels_when_fit():
    report = _report(8, 3)
    result = bounded_evidence_context(report, max_chars=4800)
    assert result.compacted
    assert len(result.text) <= 4800
    assert result.topic_total == 24
    assert result.topic_included == 24
    assert not result.topics_omitted
    assert "[00:00:00]" in result.text
    assert "[00:35:00]" in result.text


def test_budget_rejects_invalid_tiny_limit():
    try:
        bounded_evidence_context(_report(1), max_chars=200)
    except ValueError as error:
        assert "max_chars" in str(error)
    else:
        raise AssertionError("A too-small budget must be refused")


def test_long_video_generator_forces_review_and_bounds_all_retries():
    src = (
        Path(__file__).resolve().parents[1] /
        "src/rg_youtube_control/free_tools.py"
    ).read_text(encoding="utf-8")
    assert "bounded_evidence_context(evidence_report)" in src
    assert "transcript = verified_evidence" in src
    assert '"timeline_prompt_omitted_count": len(prompt_topics_omitted)' in src
    assert '"timeline_prompt_detail_shortened": prompt_detail_shortened' in src
    assert "or prompt_detail_shortened" in src
    assert "or bool(prompt_topics_omitted)" in src
    assert "Карта довгого відео скорочена" in src
