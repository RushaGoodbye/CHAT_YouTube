"""Deep-archive NAS/YouTube work is worker-only, quota-capped and draft-only."""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _seed(conn, profile, video_id, issues):
    conn.execute(
        "INSERT INTO videos(video_id,profile,title,privacy_status,"
        "audit_json,views,last_synced_at) VALUES(?,?,?,?,?,?,?)",
        (video_id, profile, "Archive example", "public",
         json.dumps({"issues": issues}), 200, "2026-10-24"),
    )
    conn.commit()


def test_deep_worker_exports_atomic_manifest_and_respects_caption_limit(
    tmp_path, monkeypatch,
):
    from rg_youtube_control.db import connect
    from rg_youtube_control import deep_archive_worker as mod

    conn = connect(tmp_path / "videos.db")
    transcripts = tmp_path / "srt"
    packages = tmp_path / "packages"
    transcripts.mkdir()
    packages.mkdir()
    video_a, video_b = "QADEEP00001", "QADEEP00002"
    assert len(video_a) == len(video_b) == 11
    _seed(conn, "main", video_a, ["no_chapters"])
    _seed(conn, "main", video_b, ["thin_description"])
    (transcripts / f"{video_a}.srt").write_text("existing SRT", encoding="utf-8")
    (packages / f"{video_a}.json").write_text(
        json.dumps({"video_id": video_a, "title": "Some title"}),
        encoding="utf-8",
    )
    observed = {"downloads": [], "uploads": [], "quota": []}

    class FakeClient:
        def __init__(self, profile):
            assert profile == "main"
        def credentials(self):
            return object()
        def download_best_caption_srt(self, video_id):
            observed["downloads"].append(video_id)
            return {"snippet": {"language": "ru"}}, "1\n00:00:01,000 --> 00:00:02,000\nText"

    monkeypatch.setattr(
        mod, "quota_budget_status", lambda _conn: {"spendable": 1000}
    )
    monkeypatch.setattr(
        mod, "record_quota_units",
        lambda _conn, cost, **kw: observed["quota"].append(cost),
    )
    try:
        result = mod.prepare_deep_review_batch(
            conn, profile="main", transcript_dir=transcripts,
            package_dir=packages, max_downloads=1,
            client_factory=FakeClient,
            uploader=lambda *a: observed["uploads"].append(a[1]),
        )
        assert result["exported"] == 2
        assert result["downloaded"] == 1
        assert observed["downloads"] == [video_b]
        assert observed["uploads"] == [video_b]
        assert observed["quota"] == [mod.CAPTION_TRANSCRIPT_COST]
        assert len(result["drafts"]) == 1
        assert result["drafts"][0]["video_id"] == video_a
        manifest_path = Path(result["path"])
        assert manifest_path.is_file()
        assert not manifest_path.with_suffix(".json.tmp").exists()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["items"][1]["transcript_ready"] is True
        assert (transcripts / f"{video_b}.srt").is_file()
        assert not (transcripts / f"{video_a}.srt.tmp").exists()
    finally:
        conn.close()


def test_deep_worker_no_quota_no_caption_fetch(tmp_path, monkeypatch):
    from rg_youtube_control.db import connect
    from rg_youtube_control import deep_archive_worker as mod

    conn = connect(tmp_path / "videos.db")
    _seed(conn, "live", "QALIVE00001", ["no_tags"])
    monkeypatch.setattr(
        mod, "quota_budget_status", lambda _conn: {"spendable": 0}
    )
    try:
        result = mod.prepare_deep_review_batch(
            conn, profile="live",
            transcript_dir=tmp_path / "offline-srt",
            package_dir=tmp_path / "packages",
            max_downloads=20,
            client_factory=lambda _: (_ for _ in ()).throw(
                AssertionError("No caption network requests allowed")
            ),
        )
        assert result["downloaded"] == 0
        assert result["exported"] == 1
        assert not result["drafts"]
    finally:
        conn.close()


def test_campaign_deep_path_never_calls_synchronous_nas_functions(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    calls = []
    try:
        monkeypatch.setattr(window, "_archive_campaign_stats_cached", lambda: {
            "main": {"deep_remaining": 1, "safe_remaining": 0},
            "live": {"deep_remaining": 0, "safe_remaining": 0},
        })
        monkeypatch.setattr(
            window, "_archive_stats_fresh_for_actions", lambda: True
        )
        monkeypatch.setattr(window, "_activate_profile", lambda profile: None)
        monkeypatch.setattr(window, "_archive_campaign_budget", lambda: {
            "deep_transcript_capacity": 1, "current_capacity": 0
        })
        for name in (
            "export_deep_review_queue_to_nas",
            "export_deep_review_transcripts",
            "import_deep_review_packages",
        ):
            monkeypatch.setattr(
                window, name, lambda *a, **kw: (_ for _ in ()).throw(
                    AssertionError("Synchronous NAS deep operation invoked")
                )
            )
        monkeypatch.setattr(
            window, "_start_deep_archive_worker",
            lambda profile, **kwargs: calls.append((profile, kwargs)) or True,
        )
        assert window.run_archive_campaign_step() is False
        assert calls == [("main", {"capacity": 1, "automatic": False})]
    finally:
        window.close()


def test_deep_worker_gui_remains_responsive(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    completed = []

    def fake_prepare(conn, **kwargs):
        time.sleep(0.17)
        return {
            "profile": "main", "exported": 0, "total": 0,
            "downloaded": 0, "drafts": [], "errors": [],
        }

    monkeypatch.setattr(ui, "prepare_deep_review_batch", fake_prepare)
    monkeypatch.setattr(
        window, "_advance_archive_campaign", lambda: completed.append(True)
    )
    try:
        start = time.monotonic()
        assert window._start_deep_archive_worker(
            "main", capacity=0, automatic=True
        )
        assert time.monotonic() - start < 0.14
        assert not window._start_deep_archive_worker(
            "main", capacity=0, automatic=True
        ), "Overlapping deep workers should be rejected"
        end = time.monotonic() + 8
        while getattr(window, "_archive_deep_worker", None) is not None:
            assert time.monotonic() < end
            app.processEvents()
            time.sleep(0.01)
        assert completed
    finally:
        worker = getattr(window, "_archive_deep_worker", None)
        if worker is not None:
            worker.wait(5000)
        window.close()


def test_caption_attempts_are_bounded_even_when_youtube_has_no_captions(
    tmp_path, monkeypatch,
):
    from rg_youtube_control.db import connect
    from rg_youtube_control import deep_archive_worker as mod

    conn = connect(tmp_path / "videos.db")
    ids = ["QADEEP00001", "QADEEP00002", "QADEEP00003"]
    for video_id in ids:
        _seed(conn, "main", video_id, ["no_chapters"])
    attempted = []

    class NoCaptionsClient:
        def __init__(self, profile):
            pass
        def credentials(self):
            return object()
        def download_best_caption_srt(self, video_id):
            attempted.append(video_id)
            raise RuntimeError("не знайдено доступних субтитрів")

    debits = []
    monkeypatch.setattr(mod, "quota_budget_status", lambda _: {"spendable": 10000})
    monkeypatch.setattr(
        mod, "record_quota_units",
        lambda _conn, cost, **kw: debits.append(cost),
    )
    try:
        result = mod.prepare_deep_review_batch(
            conn, profile="main",
            transcript_dir=tmp_path / "nonexistent",
            package_dir=tmp_path / "packages",
            max_downloads=1, client_factory=NoCaptionsClient,
        )
        assert len(attempted) == 1
        assert result["attempted_downloads"] == 1
        assert result["downloaded"] == 0
        assert debits == [50]
    finally:
        conn.close()


def test_reexport_manifest_preserves_operator_review_state(tmp_path):
    from rg_youtube_control.db import (
        connect, set_deep_review_state, deep_review_state_map
    )
    from rg_youtube_control.archive_campaign import export_deep_review_manifest

    conn = connect(tmp_path / "videos.db")
    video_id = "QAREVW00001"
    _seed(conn, "main", video_id, ["thin_description"])
    try:
        set_deep_review_state(
            conn, video_id=video_id, profile="main",
            status="review", note="operator_checked",
        )
        export_deep_review_manifest(
            conn, "main",
            transcript_dir=tmp_path / "nas-offline",
            package_dir=tmp_path / "packages",
        )
        assert deep_review_state_map(conn, "main")[video_id] == "review"
    finally:
        conn.close()
