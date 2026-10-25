"""Regression: user-confirmed TXT is not silently replaced by NAS SRT."""
from __future__ import annotations

from itertools import product
from pathlib import Path

from rg_youtube_control.seo_transcript_choice import compare_timed_to_verified


def _tokens(prefix):
    return [a + b + c + prefix for a, b, c in list(product("abcdef", repeat=3))[:60]]


def _source_pair(shared=True):
    text = "Шойгу " + " ".join(_tokens("source"))
    original = [{"start": 0.0, "duration": 0.0, "untimed": True, "text": text}]
    alternate = ("Шойгу " + " ".join(_tokens("source"))) if shared else (
        "Шойгу " + " ".join(_tokens("other"))
    )
    cues = [
        {"start": i * 12., "duration": 11., "text": alternate}
        for i in range(18)
    ]
    return original, cues


def test_faithful_timed_source_is_offered_but_not_auto_selected():
    manual, timed = _source_pair()
    result = compare_timed_to_verified(
        "Увольнение Шойгу — коррупция или план?", manual, timed,
        published_duration=217,
    )
    assert result.offer_timed
    assert result.reason == "verified_candidate"
    assert result.timed_cues == 18
    assert result.last_second == 215
    assert manual[0]["untimed"] is True  # no mutation


def test_different_conversation_with_same_named_subject_is_not_accepted():
    manual, timed = _source_pair(shared=False)
    result = compare_timed_to_verified("Увольнение Шойгу?", manual, timed)
    assert not result.offer_timed
    assert result.reason == "content_mismatch"


def test_timed_track_missing_named_subject_does_not_override_text():
    manual, timed = _source_pair()
    for cue in timed:
        cue["text"] = cue["text"].replace("Шойгу", "Погода")
    result = compare_timed_to_verified("Увольнение Шойгу?", manual, timed)
    assert not result.offer_timed
    assert result.reason == "subject_mismatch"


def test_partial_caption_coverage_is_not_offered():
    manual, timed = _source_pair()
    result = compare_timed_to_verified(
        "Увольнение Шойгу?", manual, timed, published_duration=1000,
    )
    assert not result.offer_timed
    assert result.reason == "short_coverage"


def test_untimed_candidate_is_not_offered():
    manual, timed = _source_pair()
    for cue in timed:
        cue["start"] = 0.0
        cue["duration"] = 0.0
    result = compare_timed_to_verified("Увольнение Шойгу?", manual, timed)
    assert not result.offer_timed
    assert result.reason == "incomplete_timing"


def test_desktop_only_switches_with_explicit_confirmation_and_worker_rechecks():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    pre = source.split("    def local_seo_selected(", 1)[1].split("    def _save_local_seo_result(", 1)[0]
    worker = source.split("    def _generate_local_seo_result(", 1)[1].split("\n    def ", 1)[0]
    assert 'transcript_preference = ""' in pre
    assert "QMessageBox.question(" in pre
    assert "transcript_preference = source_key" in pre
    assert "if transcript_preference:" in worker
    assert "compare_timed_to_verified(" in worker
    assert '"operator-confirmed-" + candidate_label' in worker
    assert "find_local_transcript(" in worker


def test_preflight_offers_timed_only_with_explicit_user_yes(monkeypatch, tmp_path):
    import sqlite3
    import rg_youtube_control.ui as ui

    original, timed = _source_pair()
    video_id = "MEitKm687xo"
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE videos(video_id TEXT, profile TEXT, title TEXT, duration TEXT)"
    )
    conn.execute(
        "INSERT INTO videos VALUES (?,?,?,?)",
        (video_id, "main", "Увольнение Шойгу?", "217"),
    )

    class MessageBox:
        class StandardButton:
            Yes = 1
            No = 2
        questions = []
        reply = 1

        @classmethod
        def question(cls, *args, **kwargs):
            cls.questions.append(args)
            return cls.reply

    class Window:
        data_dir = tmp_path
        current_profile = "main"

        def __init__(self):
            self.conn = conn
            self.received = []

        def _nas_path(self, key, default):
            return tmp_path / "nas"

        def _selected_optimization_video_ids(self):
            return [video_id]

        def _generate_local_seo_result(self, video_id, *, on_progress=None,
                                       transcript_preference=""):
            self.received.append(transcript_preference)
            return {"video_id": video_id}

        def _save_local_seo_result(self, result):
            assert result["video_id"] == video_id

        def _run_local_tool(self, title, task, save):
            save(task())

    monkeypatch.setattr(ui, "QMessageBox", MessageBox)
    monkeypatch.setattr(
        ui, "load_verified_text",
        lambda data_dir, selected: (original, "manual-confirmed-untimed-text")
    )
    monkeypatch.setattr(
        ui, "find_local_transcript",
        lambda folder, selected: (
            (timed, "nas-srt") if Path(folder).name == "nas" else ([], "")
        ),
    )
    window = Window()
    ui.MainWindow.local_seo_selected(window)
    assert window.received == ["nas-srt"]
    assert len(MessageBox.questions) == 1
    assert original[0]["untimed"] is True

    # "No" retains original verified text; no new preference is supplied.
    MessageBox.reply = MessageBox.StandardButton.No
    ui.MainWindow.local_seo_selected(window)
    assert window.received == ["nas-srt", ""]
    conn.close()


def test_preflight_rejects_unrelated_same_subject_srt_without_prompt(
    monkeypatch, tmp_path,
):
    import sqlite3
    import rg_youtube_control.ui as ui

    manual, unrelated = _source_pair(shared=False)
    video_id = "MEitKm687xo"
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE videos(video_id TEXT, profile TEXT, title TEXT, duration TEXT)"
    )
    conn.execute(
        "INSERT INTO videos VALUES (?,?,?,?)",
        (video_id, "main", "Увольнение Шойгу?", "217"),
    )

    class MessageBox:
        class StandardButton:
            Yes = 1
            No = 2
        @staticmethod
        def question(*args, **kwargs):
            raise AssertionError("Unrelated captions must not be suggested")

    class Window:
        data_dir = tmp_path
        current_profile = "main"

        def __init__(self):
            self.conn = conn
            self.received = []

        def _nas_path(self, key, default):
            return tmp_path / "nas"

        def _selected_optimization_video_ids(self):
            return [video_id]

        def _generate_local_seo_result(self, video_id, *, on_progress=None):
            self.received.append(video_id)
            return {"video_id": video_id}

        def _save_local_seo_result(self, result):
            assert result["video_id"] == video_id

        def _run_local_tool(self, title, task, save):
            save(task())

    monkeypatch.setattr(ui, "QMessageBox", MessageBox)
    monkeypatch.setattr(
        ui, "load_verified_text",
        lambda data_dir, selected: (manual, "manual-confirmed-untimed-text")
    )
    monkeypatch.setattr(
        ui, "find_local_transcript",
        lambda folder, selected: (
            (unrelated, "nas-srt") if Path(folder).name == "nas" else ([], "")
        ),
    )
    window = Window()
    ui.MainWindow.local_seo_selected(window)
    assert window.received == [video_id]
    conn.close()


def test_duration_formats_preserve_caption_coverage_checks():
    from rg_youtube_control.seo_transcript_choice import published_duration_seconds
    assert published_duration_seconds("PT9M53S") == 593
    assert published_duration_seconds("PT1H25M2S") == 5102
    assert published_duration_seconds("00:09:53") == 593
    assert published_duration_seconds("09:53") == 593
    assert published_duration_seconds(593) == 593
    assert published_duration_seconds("untrusted") == 0


def test_iso8601_duration_blocks_partial_timed_track():
    from rg_youtube_control.seo_transcript_choice import published_duration_seconds
    manual, timed = _source_pair()
    result = compare_timed_to_verified(
        "Увольнение Шойгу?", manual, timed,
        published_duration=published_duration_seconds("PT9M53S"),
    )
    assert not result.offer_timed
    assert result.reason == "short_coverage"
