import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from rg_youtube_control.cached_metadata import (
    cached_public_metadata,
    yt_dlp_auth_blocked,
    _cached_duration_seconds,
)
from rg_youtube_control.db import connect


VIDEO = "QCIuLwQm4nU"


def _seed(conn, *, video_id=VIDEO, scheduled=None):
    conn.execute(
        """INSERT INTO videos (
               video_id, profile, title, duration, views, privacy_status,
               scheduled_publish_at, last_synced_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, "main", "ЧАТ РУЛЕТКА: РОССИЯНЕ О ПЕРУНЕ", "35:25",
         8627, "public", scheduled, "2026-10-08T10:00:00Z"),
    )
    conn.execute(
        """INSERT INTO metadata_history (
               video_id, title, description, tags_json, reason, created_at
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (video_id, "original", "Раніше опублікований опис.",
         json.dumps(["старый тег", "чат рулетка"]), "sync",
         "2026-10-08T10:00:00Z"),
    )
    conn.execute(
        """INSERT INTO optimization_drafts (
               video_id, new_title, description, tags_json,
               source_title, source_description, source_tags_json,
               updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, "Нова назва чернетки", "Не публікувати: AI опис",
         '["новий AI тег"]', "ЧАТ РУЛЕТКА: РОССИЯНЕ О ПЕРУНЕ",
         "Повний оригінальний опис про Перуна.",
         json.dumps(["Перун", "чат рулетка"]), "2026-10-08T10:00:00Z"),
    )
    conn.commit()


def test_local_metadata_prioritizes_original_source_not_generated_draft(tmp_path):
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    data = cached_public_metadata(conn, VIDEO, "main")
    assert data["source"] == "sqlite-cache"
    assert data["title"] == "ЧАТ РУЛЕТКА: РОССИЯНЕ О ПЕРУНЕ"
    assert data["description"] == "Повний оригінальний опис про Перуна."
    assert data["tags"] == ["Перун", "чат рулетка"]
    assert "Не публікувати" not in str(data)
    assert data["duration"] == 2125
    assert data["youtube_data_api_quota"] == 0
    assert data["_caption_tracks"] == {}
    assert cached_public_metadata(conn, VIDEO, "live") == {}


def test_source_fallback_uses_history_but_never_generated_draft(tmp_path):
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    conn.execute(
        "UPDATE optimization_drafts SET source_description='',source_tags_json='[]'"
    )
    conn.commit()
    data = cached_public_metadata(conn, VIDEO, "main")
    assert data["description"] == "Раніше опублікований опис."
    assert data["tags"] == ["старый тег", "чат рулетка"]


@pytest.mark.parametrize("duration, expected", [
    ("01:03:25", 3805), ("35:25", 2125), ("PT1H3M25S", 3805),
    ("PT33S", 33), ("", 0), ("n/a", 0), ("3600", 3600),
])
def test_duration_cached_formats(duration, expected):
    assert _cached_duration_seconds(duration) == expected


def test_ytdlp_auth_challenge_detection():
    assert yt_dlp_auth_blocked(
        "ERROR: [youtube] QCIuLwQm4nU: Sign in to confirm you're not a bot "
        "Use --cookies-from-browser"
    )
    assert not yt_dlp_auth_blocked("local model returned no valid JSON")



@pytest.mark.parametrize("scenario", [
    "nas_srt_available",
    "captions_api_available",
    "yt_dlp_blocked",
    "scheduled_stream",
])
def test_legacy_local_seo_never_runs_or_fetches_network(
    monkeypatch, tmp_path, scenario,
):
    """Captions may still be used as SRT; they must not feed a local SEO generator."""
    import rg_youtube_control.ui as ui

    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(
        conn,
        scheduled="2026-10-11T21:00:00+03:00"
        if scenario == "scheduled_stream" else None,
    )
    baseline = conn.execute("SELECT COUNT(*) FROM optimization_drafts").fetchone()[0]
    conn.close()

    if scenario == "nas_srt_available":
        transcripts = tmp_path / "transcripts"
        transcripts.mkdir()
        (transcripts / f"{VIDEO}.srt").write_text(
            "1\\n00:00:00,000 --> 00:00:04,000\\n"
            "Поговорим про Перуна и веру в России.\\n",
            encoding="utf-8",
        )

    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "Legacy local SEO may not call YouTube, captions or AI"
        )

    monkeypatch.setattr(ui, "fetch_public_metadata", forbidden)
    monkeypatch.setattr(ui, "fetch_transcript", forbidden)
    monkeypatch.setattr(ui, "generate_seo_package_local", forbidden)
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")

    with pytest.raises(RuntimeError, match="vidIQ"):
        ui.MainWindow._generate_local_seo_result(state, VIDEO)

    conn = connect(tmp_path / "rg_youtube_control.db")
    assert conn.execute(
        "SELECT COUNT(*) FROM optimization_drafts"
    ).fetchone()[0] == baseline
    conn.close()
    assert not (tmp_path / "seo_evidence").exists()
