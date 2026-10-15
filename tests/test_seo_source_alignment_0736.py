"""Regression for the 2026-10-15 Shoigu screenshot: wrong NAS topic must not pass."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import rg_youtube_control.ui as ui
from rg_youtube_control.seo_source_alignment import (
    check_title_against_transcript,
    check_title_variants_against_primary_subject,
)

VIDEO_ID = "MEitKm687xo"
TITLE = "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"
WRONG_SOURCE = (
    "Идентификация собеседников, поведение в России и отношения между народами. "
    "Политическая ситуация и война в Чечне. Позиция про добровольцев и контрактников. "
    "Критика поведения в Дагестане через случай с бесплатной едой."
)


def test_screenshot_source_cannot_validate_shoigu_title():
    result = check_title_against_transcript(TITLE, WRONG_SOURCE)
    assert result.passed is False
    assert result.missing == ("Шойгу",)


def test_source_can_support_named_subject_with_real_quote():
    result = check_title_against_transcript(
        TITLE, WRONG_SOURCE + " Мы говорим про увольнение Шойгу и коррупцию.",
    )
    assert result.passed is True


def test_original_named_title_does_not_license_unrelated_ab_headlines():
    titles = [
        "Увольнение ШОЙГУ: коррупция или план?",
        "Бандиты? Идентификация собеседника в кризисе",
        "Война в Чечне: осадок и реальность",
        "Бесплатная еда и гордость: поведение в Дагестане",
    ]
    result = check_title_variants_against_primary_subject(TITLE, titles)
    assert result.anchors == ("Шойгу",)
    assert result.missing == ("варіант 2", "варіант 3", "варіант 4")


def test_ukrainian_russian_aliases_and_absence_of_topic_names():
    result = check_title_against_transcript(
        "ЗЕЛЕНСЬКИЙ проти ПУТІНА",
        "Зеленский обсуждал встречу с Путиным.",
    )
    assert result.passed
    assert check_title_against_transcript(
        "Різні думки про економіку",
        "Говоримо про зарплати.",
    ).passed


def test_no_title_only_evidence_in_source_text():
    result = check_title_against_transcript(
        "Шойгу и Путин",
        "Новости о Путине, без других имен.",
    )
    assert result.missing == ("Шойгу",)


def test_e2e_mismatched_nas_blocked_before_expensive_ollama(tmp_path, monkeypatch):
    db_path = tmp_path / "rg_youtube_control.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE videos "
            "(video_id TEXT, profile TEXT, scheduled_publish_at TEXT, "
            "privacy_status TEXT, title TEXT, duration INTEGER)"
        )
        conn.execute("CREATE TABLE settings (key TEXT, value TEXT)")
        conn.execute(
            "INSERT INTO videos VALUES (?, 'main', NULL, 'public', ?, 600)",
            (VIDEO_ID, TITLE),
        )
        conn.execute(
            "INSERT INTO settings VALUES ('nas_transcripts_path', ?)",
            (str(tmp_path),),
        )

    rows = [
        {"start": 12.0, "duration": 200.0, "text": WRONG_SOURCE[:165]},
        {"start": 312.0, "duration": 150.0, "text": WRONG_SOURCE[165:]},
    ]
    monkeypatch.setattr(
        ui, "cached_public_metadata",
        lambda conn, vid, profile: {
            "title": TITLE, "description": "", "tags": [],
            "duration": 600,
        },
    )
    monkeypatch.setattr(
        ui, "find_local_transcript",
        lambda folder, video_id: (rows, "nas-srt"),
    )
    called = []
    monkeypatch.setattr(
        ui, "analyze_all_timeline_blocks",
        lambda *args, **kw: called.append("analysis"),
    )
    monkeypatch.setattr(
        ui, "generate_seo_package_local",
        lambda **kw: called.append("generate"),
    )
    stub = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    with pytest.raises(RuntimeError, match="транскрипт не підтверджує"):
        ui.MainWindow._generate_local_seo_result(stub, VIDEO_ID)

    assert called == []
    assert not (tmp_path / "seo_evidence").exists()


def test_internal_validation_runs_before_preview_and_save():
    from pathlib import Path
    src = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    fn = src.split("    def _generate_local_seo_result(", 1)[1]
    fn = fn.split("\n    def ", 1)[0]
    assert fn.index("source_alignment = check_title_against_transcript(") < fn.index(
        "analyze_all_timeline_blocks("
    )
    assert fn.index("title_alignment = check_title_variants_against_primary_subject(") < fn.index(
        'return {\n            "video_id"'
    )
