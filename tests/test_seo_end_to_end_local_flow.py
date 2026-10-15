"""Behavior-level SEO source-selection regression tests.

Run the real MainWindow handler on a lightweight stand-in so none of the
Windows test cases need NAS access, real YouTube, Whisper models or UI clicks.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import rg_youtube_control.ui as ui
from rg_youtube_control.free_tools import load_srt_transcript
from rg_youtube_control.offline_transcription import generate_srt_offline


VIDEO_ID = "MEitKm687xo"


class StubWindow:
    def __init__(self, root):
        self.data_dir = root
        self.current_profile = "main"
        self.runs = []
        self.saved = []
        (root / "nas").mkdir(parents=True, exist_ok=True)

    def _selected_optimization_video_ids(self):
        return [VIDEO_ID]

    def _nas_path(self, key, default):
        return self.data_dir / "nas"

    def _generate_local_seo_result(self, video_id, *, on_progress=None):
        rows = load_srt_transcript(self.data_dir / "nas" / f"{video_id}.srt")
        assert rows, "Transcription must be created before SEO"
        return {"video_id": video_id, "transcript_rows": rows}

    def _save_local_seo_result(self, result):
        self.saved.append(result)

    def _run_local_tool(self, title, task, save):
        self.runs.append(title)
        save(task())


class FakeMessages:
    class StandardButton:
        Yes = 1
        No = 2

    notices = []
    confirmed = True

    @classmethod
    def question(cls, *args, **kwargs):
        return cls.StandardButton.Yes if cls.confirmed else cls.StandardButton.No

    @classmethod
    def information(cls, parent, title, content, *args, **kwargs):
        cls.notices.append((title, content))


class FakePicker:
    chosen = ""
    chosen_model = ""

    @classmethod
    def getOpenFileName(cls, *args, **kwargs):
        return cls.chosen, ""

    @classmethod
    def getExistingDirectory(cls, *args, **kwargs):
        return cls.chosen_model


@pytest.fixture
def environment(monkeypatch, tmp_path):
    FakePicker.chosen = ""
    FakePicker.chosen_model = ""
    FakeMessages.notices = []
    FakeMessages.confirmed = True
    monkeypatch.setattr(ui, "QMessageBox", FakeMessages)
    monkeypatch.setattr(ui, "QFileDialog", FakePicker)
    monkeypatch.setattr(ui, "find_exact_local_media", lambda video_id, roots: None)
    monkeypatch.setattr(ui, "historical_media_candidates", lambda conn, video_id, roots: [])
    monkeypatch.setattr(ui, "get_verified_media", lambda path, video_id: None)
    # The handler consults history before the file chooser.
    import sqlite3
    with sqlite3.connect(str(tmp_path / "rg_youtube_control.db")) as db:
        db.execute("CREATE TABLE videos (video_id TEXT, title TEXT)")
        db.execute("CREATE TABLE metadata_history (video_id TEXT, title TEXT, created_at TEXT)")
    monkeypatch.setenv("RG_SEO_WHISPER_MODEL_DIR", str(tmp_path / "model"))
    return StubWindow(tmp_path)


def test_cancelled_file_picker_does_not_start_worker(environment):
    ui.MainWindow.local_seo_selected(environment)
    assert not environment.runs
    assert FakeMessages.notices[0][0] == "SEO: вихідний файл не обрано"
    assert not (environment.data_dir / "verified_media.json").exists()


def test_selected_source_missing_model_is_distinct_and_binding_preserved(environment):
    media = environment.data_dir / "renamed-after-vidiq.mp4"
    media.write_bytes(b"video")
    FakePicker.chosen = str(media)
    ui.MainWindow.local_seo_selected(environment)
    registry = json.loads((environment.data_dir / "verified_media.json").read_text(encoding="utf-8"))
    assert registry[VIDEO_ID]["path"] == str(media)
    assert registry[VIDEO_ID]["verified"] is True
    assert not environment.runs
    assert FakeMessages.notices[-1][0] == "SEO: відсутня модель Whisper"


def test_refused_source_is_not_verified(environment):
    media = environment.data_dir / "other-video.mp4"
    media.write_bytes(b"video")
    FakePicker.chosen = str(media)
    FakeMessages.confirmed = False
    ui.MainWindow.local_seo_selected(environment)
    assert not (environment.data_dir / "verified_media.json").exists()
    assert not environment.runs


def test_confirmed_source_to_srt_to_seo_worker(environment, monkeypatch):
    media = environment.data_dir / "original-unrelated-filename.mp4"
    media.write_bytes(b"video")
    FakePicker.chosen = str(media)
    model_dir = environment.data_dir / "model"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"model-placeholder")

    class FakeWhisper:
        def transcribe(self, source, **kwargs):
            assert Path(source) == media
            return iter([
                SimpleNamespace(start=2.0, end=4.0, text="Перевірений тестовий діалог")
            ]), {}

    def run_fake_whisper(*, video_id, media, destination, model_dir, on_progress=None):
        return generate_srt_offline(
            video_id=video_id, media=media, destination=destination,
            model_dir=model_dir, whisper_factory=lambda *args, **kw: FakeWhisper(),
        )
    monkeypatch.setattr(ui, "generate_srt_offline", run_fake_whisper)
    ui.MainWindow.local_seo_selected(environment)

    assert len(environment.runs) == 1
    assert environment.saved[0]["transcript_rows"]
    assert (environment.data_dir / "nas" / f"{VIDEO_ID}.srt").is_file()
    assert not FakeMessages.notices


def test_existing_srt_requires_no_model_or_file_picker(environment):
    srt = environment.data_dir / "nas" / f"{VIDEO_ID}.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,500\nРеальний текст\n", encoding="utf-8")
    ui.MainWindow.local_seo_selected(environment)
    assert environment.saved[0]["transcript_rows"]
    assert FakePicker.chosen == ""
    assert not FakeMessages.notices


def test_manual_whisper_model_selection_remembered(environment):
    media = environment.data_dir / "video-after-vidiq-rename.mp4"
    media.write_bytes(b"video")
    FakePicker.chosen = str(media)
    model_dir = environment.data_dir / "separate-model"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"local-model")
    FakePicker.chosen_model = str(model_dir)

    def fake_transcribe(*, video_id, media, destination, model_dir, on_progress=None):
        assert model_dir == environment.data_dir / "separate-model"
        target = Path(destination) / f"{video_id}.srt"
        target.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nТекст для SEO\n",
            encoding="utf-8",
        )
        return target

    import rg_youtube_control.ui as ui
    from pytest import MonkeyPatch
    with MonkeyPatch.context() as patch:
        patch.setattr(ui, "generate_srt_offline", fake_transcribe)
        ui.MainWindow.local_seo_selected(environment)
    assert len(environment.saved) == 1
    assert (
        (environment.data_dir / "whisper_model_dir.txt").read_text(encoding="utf-8")
        == str(model_dir)
    )
