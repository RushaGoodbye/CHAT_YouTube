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


def test_source_repair_uses_separate_local_srt_and_keeps_original_nas(tmp_path, monkeypatch):
    """No destructive overwrite of an incorrectly named NAS SRT."""
    import rg_youtube_control.ui as ui
    from rg_youtube_control.free_tools import load_srt_transcript

    nas = tmp_path / "nas"
    nas.mkdir()
    old_srt = nas / f"{VIDEO_ID}.srt"
    original_content = (
        "1\n00:00:00,000 --> 00:00:05,000\n"
        "Разговор о Чечне и Дагестане, без иных тем.\n"
    )
    old_srt.write_text(original_content, encoding="utf-8")

    media = tmp_path / "renamed-vidiq-original.mp4"
    media.write_bytes(b"video")
    model = tmp_path / "whisper-model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"model")
    monkeypatch.setenv("RG_SEO_WHISPER_MODEL_DIR", str(model))

    class Messages:
        class StandardButton:
            Yes = 1
            No = 2
        @classmethod
        def question(cls, *args, **kwargs):
            return cls.StandardButton.Yes
        @classmethod
        def information(cls, *args, **kwargs):
            raise AssertionError("No information dialog expected")
        @classmethod
        def warning(cls, *args, **kwargs):
            raise AssertionError("No warning expected")

    class Picker:
        @classmethod
        def getOpenFileName(cls, *args, **kwargs):
            return str(media), ""
        @classmethod
        def getExistingDirectory(cls, *args, **kwargs):
            return str(model)

    class Window:
        data_dir = tmp_path
        current_profile = "main"
        saved = None
        conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(
            fetchone=lambda: {"title": TITLE},
        ))

        def _selected_optimization_video_ids(self):
            return [VIDEO_ID]

        def _nas_path(self, *args):
            return nas

        def _generate_local_seo_result(self, video_id, *, on_progress=None):
            repaired = self.data_dir / "seo_verified_transcripts" / f"{video_id}.srt"
            rows = load_srt_transcript(repaired)
            assert rows and "Шойгу" in rows[0]["text"]
            return {"video_id": video_id}

        def _save_local_seo_result(self, result):
            self.saved = result

        def _run_local_tool(self, label, task, callback):
            callback(task())

    def fake_whisper(*, video_id, media, destination, model_dir, on_progress=None):
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"{video_id}.srt"
        path.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\n"
            "Шойгу обсуждают после смены должности.\n",
            encoding="utf-8",
        )
        return path

    class SourcePicker:
        @staticmethod
        def getItem(*args, **kwargs):
            return "Вибрати вихідний відеофайл для Whisper", True

    monkeypatch.setattr(ui, "QMessageBox", Messages)
    monkeypatch.setattr(ui, "QInputDialog", SourcePicker)
    monkeypatch.setattr(ui, "QFileDialog", Picker)
    monkeypatch.setattr(ui, "generate_srt_offline", fake_whisper)
    stub = Window()
    ui.MainWindow.local_seo_selected(stub)
    assert stub.saved == {"video_id": VIDEO_ID}
    assert old_srt.read_text(encoding="utf-8") == original_content
    assert (tmp_path / "seo_verified_transcripts" / f"{VIDEO_ID}.srt").exists()


def test_named_subject_must_appear_in_verified_quotes_not_only_original_title(
    tmp_path, monkeypatch,
):
    """A single mention outside quoted topics cannot authorize off-topic A/B."""
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
    rows = [
        {"start": 12.0, "duration": 120.0,
         "text": "Шойгу. Обсуждаем политическую ситуацию."},
        {"start": 312.0, "duration": 120.0,
         "text": "Жизнь в Дагестане и отношения между народами."},
    ]
    monkeypatch.setattr(
        ui, "cached_public_metadata",
        lambda *args: {"title": TITLE, "description": "",
                       "tags": [], "duration": 600},
    )
    monkeypatch.setattr(
        ui, "find_local_transcript",
        lambda *args: (rows, "nas-srt"),
    )
    monkeypatch.setattr(
        ui, "analyze_all_timeline_blocks",
        lambda *args, **kwargs: {
            "blocks_with_evidence": 1, "blocks_total": 1,
            "blocks": [{"verified": True, "topics": [
                {"topic": "Дагестан",
                 "evidence": "Жизнь в Дагестане и отношения между народами."}
            ]}],
        },
    )
    called = []
    monkeypatch.setattr(
        ui, "generate_seo_package_local",
        lambda **kwargs: called.append(1),
    )
    stub = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    with pytest.raises(RuntimeError, match="підтверджені цитати"):
        ui.MainWindow._generate_local_seo_result(stub, VIDEO_ID)
    assert not called
