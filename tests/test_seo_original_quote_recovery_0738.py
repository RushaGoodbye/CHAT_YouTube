"""0.7.38 regression: do not reject a real Shoigu transcript for model omission."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import rg_youtube_control.ui as ui
from rg_youtube_control.dialogue_seo import split_timeline
from rg_youtube_control.seo_original_quote_recovery import (
    recover_omitted_named_quotes,
)
from rg_youtube_control.seo_source_alignment import check_title_against_transcript

VIDEO_ID = "MEitKm687xo"
TITLE = "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"
REAL_TEXT = (
    "Мы пытаемся узнать настоящую причину увольнения Шойгу: "
    "коррупция или всё идёт по плану. Один россиянин считает, "
    "что Шойгу и Путин в хороших отношениях. "
    "Следующий собеседник спорит о роли Белоусова и военных расходах. "
    "Речь идёт о коррупции, заместителях Шойгу и Тимуре Иванове. "
)
OFF_TOPIC = "Разговор о политической ситуации, войне в Чечне и Дагестане."


def report_for(rows, *, chosen_quote=OFF_TOPIC):
    blocks = split_timeline(rows)
    return {
        "blocks_total": len(blocks),
        "blocks_analyzed": len(blocks),
        "blocks_with_evidence": len(blocks),
        "unverified_blocks": [],
        "blocks": [
            {
                "index": b["index"],
                "start_stamp": b["start_stamp"],
                "end_stamp": b["end_stamp"],
                "untimed": b.get("untimed", False),
                "verified": True,
                "topics": [{
                    "topic": "Політична ситуація",
                    "summary_uk": "Співрозмовники сперечаються про політичну ситуацію.",
                    "evidence": chosen_quote,
                }],
            }
            for b in blocks
        ],
        "needs_review": False,
    }


def test_exact_shoigu_quote_restores_model_omission_with_editorial_flag():
    rows = [{
        "start": 0, "duration": 0, "untimed": True,
        "text": REAL_TEXT + OFF_TOPIC + " " + REAL_TEXT,
    }]
    raw = report_for(rows)
    updated, recovered = recover_omitted_named_quotes(raw, rows, TITLE)
    assert recovered == ("Шойгу",)
    assert updated["needs_review"] is True
    assert len(updated["source_anchor_recovery"]) == 1
    original_excerpt = updated["source_anchor_recovery"][0]["quote"]
    assert "Шойгу" in original_excerpt
    assert original_excerpt in rows[0]["text"]
    assert any(key in original_excerpt.casefold() for key in ("увольн", "корруп"))
    assert check_title_against_transcript(
        TITLE,
        " ".join(topic["evidence"] for block in updated["blocks"]
                 for topic in block["topics"]),
    ).passed
    assert updated["blocks"][0]["untimed"] is True
    assert updated["blocks"][0]["start_stamp"] == "без таймкоду"
    assert updated["blocks"][0]["topics"][-1]["origin"] == (
        "verbatim-original-transcript-recovery"
    )
    assert "source_anchor_recovery" not in raw
    assert raw["needs_review"] is False


def test_single_name_drop_without_dismissal_or_corruption_remains_blocked():
    rows = [{
        "start": 0, "duration": 0, "untimed": True,
        "text": "Шойгу. " + OFF_TOPIC * 5,
    }]
    updated, recovered = recover_omitted_named_quotes(
        report_for(rows), rows, TITLE,
    )
    assert recovered == ()
    assert not updated.get("source_anchor_recovery")


def test_empty_original_cannot_invent_evidence():
    rows = [{"start": 0, "duration": 0,
             "text": OFF_TOPIC * 5, "untimed": True}]
    updated, recovered = recover_omitted_named_quotes(
        report_for(rows), rows, TITLE,
    )
    assert not recovered
    assert all("Шойгу" not in p["evidence"]
               for b in updated["blocks"] for p in b["topics"])


def test_scans_later_mentions_if_first_is_in_unrelated_context():
    rows = [{
        "start": 0, "duration": 0, "untimed": True,
        "text": "Шойгу. " + OFF_TOPIC * 4 + " " + REAL_TEXT,
    }]
    updated, recovered = recover_omitted_named_quotes(
        report_for(rows), rows, TITLE,
    )
    assert recovered == ("Шойгу",)
    assert "увольнения Шойгу" in updated["source_anchor_recovery"][0]["quote"]


def test_mismatch_in_analysis_block_count_fails_closed():
    rows = [{"start": 0, "duration": 0, "text": REAL_TEXT * 2,
             "untimed": True}]
    fake = report_for(rows)
    fake["blocks"].append(dict(fake["blocks"][0]))
    _, recovered = recover_omitted_named_quotes(fake, rows, TITLE)
    assert not recovered


def test_ui_real_transcript_keeps_recovered_evidence_in_saved_map(
    tmp_path, monkeypatch,
):
    with sqlite3.connect(tmp_path / "rg_youtube_control.db") as conn:
        conn.execute(
            "CREATE TABLE videos (video_id TEXT, profile TEXT, "
            "scheduled_publish_at TEXT, privacy_status TEXT, "
            "title TEXT, duration INTEGER)"
        )
        conn.execute("CREATE TABLE settings (key TEXT, value TEXT)")
        conn.execute(
            "INSERT INTO videos VALUES (?, 'main', NULL, 'public', ?, 593)",
            (VIDEO_ID, TITLE),
        )
    rows = [{"start": 0, "duration": 0, "untimed": True,
             "text": REAL_TEXT * 4 + " " + OFF_TOPIC}]
    monkeypatch.setattr(
        ui, "cached_public_metadata",
        lambda *_: {"title": TITLE, "description": "", "tags": [],
                    "duration": 593},
    )
    monkeypatch.setattr(
        ui, "load_verified_text",
        lambda *args: (rows, "manual-confirmed-untimed-text"),
    )
    monkeypatch.setattr(
        ui, "find_local_transcript",
        lambda *args: pytest.fail("NAS should never be opened"),
    )
    monkeypatch.setattr(
        ui, "analyze_all_timeline_blocks",
        lambda *args, **kwargs: report_for(rows),
    )
    monkeypatch.setattr(
        ui, "generate_seo_package_local",
        lambda **kwargs: {
            "title": "ЗВІЛЬНЕННЯ ШОЙГУ: КОРУПЦІЯ ЧИ ПЛАН?",
            "title_variants": [
                "ШОЙГУ І КОРУПЦІЯ: ЧОМУ ЗМІНИЛИ МІНІСТРА?",
                "ШОЙГУ ПІШОВ З ПОСАДИ: ЩО ДУМАЮТЬ РОСІЯНИ?",
                "ШОЙГУ ТА БІЛОУСОВ: КУДИ ВЕДЕ ЦЯ ЗАМІНА?",
            ],
            "description": "Тест редакторської чернетки",
            "needs_review": False,
        },
    )
    stub = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    result = ui.MainWindow._generate_local_seo_result(
        stub, VIDEO_ID,
    )
    assert result["package"]["needs_review"] is True
    assert "оригіналу" in result["package"]["review_reason"]
    assert result["package"]["chapters"] == ""
    assert result["evidence_report"]["source_anchor_recovery"]
    assert result["evidence_report"]["untimed"] is True
    assert (
        tmp_path / "seo_evidence" / f"{VIDEO_ID}.json"
    ).is_file()
