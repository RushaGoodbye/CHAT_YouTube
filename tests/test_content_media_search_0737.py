"""Regression checks for duration/speech candidate discovery without auto-binding."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rg_youtube_control.media_content_matching import shortlist_local_media
from rg_youtube_control.media_sampled_speech import annotate_sampled_speech


def test_wrong_name_but_exact_duration_finds_original_and_ignores_unrelated(tmp_path):
    renamed = tmp_path / "774-03.mp4"
    unrelated = tmp_path / "Новый заголовок ШОЙГУ.mp4"
    renamed.write_bytes(b"file")
    unrelated.write_bytes(b"file")
    lengths = {renamed: 599.0, unrelated: 1800.0}
    candidates = shortlist_local_media(
        roots=[tmp_path], expected_seconds=600,
        title="Увольнение ШОЙГУ - коррупция или все идет по плану?",
        cache_path=tmp_path / "index.json",
        duration_reader=lambda p: lengths[p],
    )
    assert [x.path for x in candidates] == [renamed]
    assert candidates[0].duration_delta == 1
    assert not candidates[0].speech_subject


def test_sidecar_provides_content_signal_but_never_verifies_media_id(tmp_path):
    a = tmp_path / "old_cut.mp4"
    b = tmp_path / "new_cut.mp4"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    (a.with_suffix(".srt")).write_text(
        "1\n00:00:01,000 --> 00:00:06,000\n"
        "Мы обсуждаем увольнение Шойгу сегодня.\n", encoding="utf-8"
    )
    (b.with_suffix(".srt")).write_text(
        "1\n00:00:01,000 --> 00:00:06,000\n"
        "Рассказываем о Дагестане.\n", encoding="utf-8"
    )
    result = shortlist_local_media(
        roots=[tmp_path], expected_seconds=600, title="УВОЛЬНЕНИЕ ШОЙГУ?",
        duration_reader=lambda _: 600,
    )
    assert result[0].path == a
    assert result[0].sidecar_subject is True
    assert result[0].speech_subject is False
    assert result[1].sidecar_subject is False


def test_offline_or_unknown_duration_cannot_pick_media(tmp_path):
    path = tmp_path / "candidate.mp4"
    path.write_bytes(b"x")
    assert shortlist_local_media(
        roots=[tmp_path], expected_seconds=0, title="Шойгу",
        duration_reader=lambda _: 600,
    ) == []
    assert shortlist_local_media(
        roots=[tmp_path / "NAS_offline"], expected_seconds=600,
        title="Шойгу", duration_reader=lambda _: 600,
    ) == []


def test_duration_cache_is_reused_and_invalidated_on_file_change(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"0")
    probe_calls = []

    def probe(path):
        probe_calls.append(path)
        return 600

    opts = dict(
        roots=[tmp_path], expected_seconds=600, title="Шойгу",
        cache_path=tmp_path / "index.json", duration_reader=probe,
    )
    shortlist_local_media(**opts)
    shortlist_local_media(**opts)
    assert probe_calls == [media]
    media.write_bytes(b"01")
    shortlist_local_media(**opts)
    assert probe_calls == [media, media]


def test_short_audio_whisper_ranks_speech_about_named_subject(tmp_path):
    media1 = tmp_path / "unknown.mp4"
    media2 = tmp_path / "candidate.mp4"
    fake = dict(
        path=media1, duration=600.0, duration_delta=1.0, title_score=0.1,
        sidecar_excerpt="", sidecar_subject=False,
    )
    from rg_youtube_control.media_content_matching import MediaCandidate
    items = [
        MediaCandidate(**fake),
        MediaCandidate(**{**fake, "path": media2, "duration_delta": 2.0}),
    ]
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"local")

    class MockModel:
        def transcribe(self, audio, **kwargs):
            text = "Обсуждаем Шойгу и коррупцию." if audio == 2 else "О ценах."
            return iter([SimpleNamespace(text=text)]), {}

    result = annotate_sampled_speech(
        items, model_dir=model_dir, title="Шойгу и коррупция",
        model_factory=lambda *args, **kwargs: MockModel(),
        audio_reader=lambda path, **kwargs: 2 if path == media2 else 1,
    )
    assert result[0].path == media2
    assert result[0].speech_subject
    assert not result[1].speech_subject


def test_no_whisper_model_still_returns_unverified_candidates(tmp_path):
    from rg_youtube_control.media_content_matching import MediaCandidate
    sample = MediaCandidate(
        path=tmp_path / "video.mp4", duration=700.0,
        duration_delta=0.0, title_score=0.0,
        sidecar_excerpt="", sidecar_subject=False,
    )
    got = annotate_sampled_speech(
        [sample], model_dir=tmp_path / "missing", title="Шойгу",
        model_factory=lambda *args, **kwargs: 1 / 0,
    )
    assert got == [sample]


def test_gui_search_is_background_and_requires_explicit_user_confirmation():
    src = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    scanner = src.split("    def _start_media_content_search(", 1)[1].split(
        "\n    def ", 1
    )[0]
    assert "shortlist_local_media(" in scanner
    assert "annotate_sampled_speech(" in scanner
    assert "self._run_local_tool(" in scanner
    assert "QDesktopServices.openUrl(" in scanner
    assert "QMessageBox.question(" in scanner
    assert scanner.index("reply != QMessageBox.StandardButton.Yes") < scanner.index(
        "save_verified_media("
    )
    assert "_seo_pending_media_repair" in scanner
    assert "QTimer.singleShot(300, self.local_seo_selected)" in scanner


def test_legacy_nas_srt_still_preserved():
    src = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    handler = src.split("    def local_seo_selected(", 1)[1].split(
        "\n    def ", 1
    )[0]
    assert "destination=confirmed_dir if repairing_wrong_source" in handler
    assert "_start_media_content_search(video_id, transcript_dir)" in handler
    assert "save_verified_media(" in src
    assert "youtube.update" not in handler
