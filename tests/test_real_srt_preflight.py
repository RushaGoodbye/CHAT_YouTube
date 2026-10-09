"""Offline checks for the read-only, anonymous real-SRT preflight."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import sys


def _pilot(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_real_srt_preflight as pilot
    return pilot


def _setup(tmp_path, with_live=True):
    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE videos (video_id TEXT, profile TEXT, scheduled_publish_at TEXT)"
    )
    conn.execute("CREATE TABLE settings (key TEXT, value TEXT)")
    conn.execute(
        "INSERT INTO videos VALUES (?, 'main', NULL)", ("QCIuLwQm4nU",)
    )
    if with_live:
        conn.execute(
            "INSERT INTO videos VALUES (?, 'live', NULL)", ("ABCDEFGHIJK",)
        )
    conn.commit()
    conn.close()

    nas = tmp_path / "transcripts"
    nas.mkdir()
    sample = (
        "1\n00:00:00,000 --> 00:00:04,000\n"
        "Питання про бензин і ціни у першому діалозі.\n\n"
        "2\n00:00:04,500 --> 00:00:09,000\n"
        "Відповідь про зміни цін і новини у другому діалозі.\n"
    )
    (nas / "QCIuLwQm4nU.srt").write_text(sample, encoding="utf-8")
    if with_live:
        (nas / "ABCDEFGHIJK.srt").write_text(sample, encoding="utf-8")
    return db, nas, sample


def test_two_profiles_validate_caption_source_without_export(tmp_path, monkeypatch):
    pilot = _pilot(monkeypatch)
    db, nas, sample = _setup(tmp_path)
    result = pilot.inspect(db_path=db, transcript_dir=nas)
    assert result["status"] == "PASS"
    assert result["profiles"]["main"]["status"] == "PASS"
    assert result["profiles"]["live"]["status"] == "PASS"
    assert result["profiles"]["main"]["caption_rows"] == 2
    assert result["transcripts_uploaded"] is False
    assert result["transcripts_logged"] is False
    assert result["semantic_quality_verified"] is False
    assert "QCIuLwQm4nU" not in str(result)
    assert "Питання про бензин" not in str(result)


def test_missing_live_srt_is_a_blocker_not_a_false_pass(tmp_path, monkeypatch):
    pilot = _pilot(monkeypatch)
    db, nas, _ = _setup(tmp_path, with_live=False)
    result = pilot.inspect(db_path=db, transcript_dir=nas)
    assert result["status"] == "PARTIAL"
    assert result["profiles"]["live"]["status"] == "NO_SAMPLE"


def test_missing_nas_and_database_fail_closed(tmp_path, monkeypatch):
    pilot = _pilot(monkeypatch)
    db, nas, _ = _setup(tmp_path)
    assert pilot.inspect(db_path=db, transcript_dir=tmp_path / "not-mounted")["status"] == "NOT_READY"
    assert pilot.inspect(db_path=tmp_path / "missing.db", transcript_dir=nas)["status"] == "NOT_READY"
