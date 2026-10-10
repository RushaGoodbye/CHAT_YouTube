import json
import os
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
from rg_youtube_control.config import normalize_nas_unc_path


VIDEO = "QCIuLwQm4nU"


def test_local_posix_srt_directory_is_preserved_on_linux(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX path handling is only relevant on Linux")
    local_path = str(tmp_path / "transcripts")
    assert normalize_nas_unc_path(local_path, r"\\server\share") == local_path



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


def test_cached_title_nas_srt_does_not_invoke_yt_dlp(monkeypatch, tmp_path):
    import rg_youtube_control.ui as ui
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / f"{VIDEO}.srt").write_text(
        "1\n00:00:00,000 --> 00:00:04,000\n"
        "Поговорим про Перуна и веру в России.\n",
        encoding="utf-8",
    )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
        ("nas_transcripts_path", str(transcript_dir)),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        ui, "fetch_public_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("yt-dlp must never run when cached metadata and NAS captions exist")
        ),
    )
    monkeypatch.setattr(
        ui, "fetch_transcript",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("NAS SRT must be preferred")
        ),
    )
    report = {
        "blocks_total": 1, "blocks_with_evidence": 1,
        "blocks": [{"start_stamp": "00:00:00", "topics": [{
            "topic": "Віра в Перуна", "summary_uk": "Розмова про релігію",
            "evidence": "Поговорим про Перуна",
        }]}],
    }
    monkeypatch.setattr(
        ui, "analyze_all_timeline_blocks", lambda *_args, **_kwargs: report
    )
    monkeypatch.setattr(
        ui, "generate_seo_package_local", lambda **kwargs: {
            "title": kwargs["current_title"],
            "description": "Український опис розмови.",
            "title_variants": [], "tags": [], "needs_review": True,
        },
    )
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    stages = []
    result = ui.MainWindow._generate_local_seo_result(
        state, VIDEO, on_progress=stages.append
    )
    assert result["context"]["source"] == "sqlite-cache"
    assert result["context"]["description"] != "Не публікувати: AI опис"
    assert result["context"]["transcript_source"] == "nas-srt"
    assert result["evidence_report"]["blocks_total"] == 1
    assert any("yt-dlp не потрібен" in stage for stage in stages)
    assert (tmp_path / "seo_evidence" / f"{VIDEO}.json").exists()


def test_captions_api_success_still_avoids_ytdlp(monkeypatch, tmp_path):
    import rg_youtube_control.ui as ui
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    conn.close()
    monkeypatch.setattr(
        ui, "fetch_public_metadata",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("Do not request cookies or scrape when transcript API works")
        ),
    )
    monkeypatch.setattr(
        ui, "fetch_transcript", lambda *_args: [
            {"text": "Обсуждение Перуна.", "start": 0.0, "duration": 4.0}
        ],
    )
    monkeypatch.setattr(
        ui, "analyze_all_timeline_blocks",
        lambda *_args, **_kwargs: {
            "blocks_total": 1, "blocks_with_evidence": 1,
            "blocks": [{"start_stamp": "00:00:00", "topics": [{
                "topic": "Віра в Перуна",
                "summary_uk": "Розмова про богів і віру",
                "evidence": "Обсуждение Перуна",
            }]}],
        },
    )
    monkeypatch.setattr(
        ui, "generate_seo_package_local", lambda **kwargs: {
            "title": kwargs["current_title"], "description": "Опис"
        },
    )
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    result = ui.MainWindow._generate_local_seo_result(state, VIDEO)
    assert result["context"]["transcript_source"] == "youtube-transcript-api"
    assert result["context"]["youtube_data_api_quota"] == 0


def test_blocked_ytdlp_without_any_captions_gives_actionable_message(monkeypatch, tmp_path):
    import rg_youtube_control.ui as ui
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    conn.close()
    monkeypatch.setattr(ui, "fetch_transcript", lambda *_args: [])
    monkeypatch.setattr(
        ui, "fetch_public_metadata",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("Sign in to confirm you're not a bot")
        ),
    )
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    with pytest.raises(RuntimeError, match="NAS SRT.*YouTube Transcript"):
        ui.MainWindow._generate_local_seo_result(state, VIDEO)
    assert not (tmp_path / "seo_evidence").exists()


def test_scheduled_stream_still_blocked_before_network(monkeypatch, tmp_path):
    import rg_youtube_control.ui as ui
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn, scheduled="2026-10-11T21:00:00+03:00")
    conn.close()
    monkeypatch.setattr(
        ui, "fetch_public_metadata",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("No metadata access for scheduled streams")
        ),
    )
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    with pytest.raises(RuntimeError, match="запланований"):
        ui.MainWindow._generate_local_seo_result(state, VIDEO)


def test_missing_original_description_is_recovered_even_with_cached_title(monkeypatch, tmp_path):
    import rg_youtube_control.ui as ui
    from rg_youtube_control.cached_metadata import merge_verified_public_source_metadata

    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    conn.execute("DELETE FROM metadata_history WHERE video_id=?", (VIDEO,))
    conn.execute(
        "UPDATE optimization_drafts SET source_description='',source_tags_json='[]' "
        "WHERE video_id=?", (VIDEO,)
    )
    conn.commit()
    cached = cached_public_metadata(conn, VIDEO, "main")
    assert cached["title"]
    assert cached["source_description_available"] is False
    conn.close()

    original = "Підтримка: https://donate.rginfoua.pp.ua"
    public = {
        "video_id": VIDEO,
        "title": "REMOTE TITLE MUST NOT REPLACE CACHED TITLE",
        "description": original,
        "tags": ["чат рулетка", "Перун"],
        "duration": 2125,
        "_caption_tracks": {},
    }
    recovered = merge_verified_public_source_metadata(cached, VIDEO, public)
    assert recovered["title"] == cached["title"]
    assert recovered["description"] == original
    assert recovered["tags"] == ["чат рулетка", "Перун"]
    assert recovered["source_description_available"] is True
    assert recovered["youtube_data_api_quota"] == 0

    probes = []
    monkeypatch.setattr(ui, "fetch_public_metadata", lambda video: (
        probes.append(video) or public
    ))
    monkeypatch.setattr(ui, "fetch_transcript", lambda _id: [{
        "text": "Поговорим про Перуна и веру в России.",
        "start": 0.0, "duration": 4.0,
    }])
    monkeypatch.setattr(ui, "analyze_all_timeline_blocks", lambda *_a, **_kw: {
        "blocks_total": 1, "blocks_with_evidence": 1, "source_integrity_verified": True,
        "blocks": [{"start_stamp": "00:00:00", "topics": [{
            "topic": "Віра в Перуна", "summary_uk": "Розмова про релігію",
            "evidence": "Поговорим про Перуна",
        }]}],
    })
    observed = {}
    def generate(**kwargs):
        observed.update(kwargs)
        return {
            "title": kwargs["current_title"],
            "description": "Оригінал збережено",
            "title_variants": [], "tags": ["Перун"], "needs_review": True,
        }
    monkeypatch.setattr(ui, "generate_seo_package_local", generate)
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    result = ui.MainWindow._generate_local_seo_result(state, VIDEO)
    assert probes == [VIDEO]
    assert observed["current_description"].startswith(original)
    assert "https://donate.rginfoua.pp.ua" in observed["current_description"]
    assert observed["current_tags"] == ["чат рулетка", "Перун"]
    assert observed["current_title"] == cached["title"]
    assert result["context"]["source_description_verified"] is True
    assert result["context"]["youtube_data_api_quota"] == 0


def test_missing_source_description_fails_closed_when_public_lookup_blocked(monkeypatch, tmp_path):
    import rg_youtube_control.ui as ui
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    conn.execute("DELETE FROM metadata_history WHERE video_id=?", (VIDEO,))
    conn.execute(
        "UPDATE optimization_drafts SET source_description='', source_tags_json='[]' "
        "WHERE video_id=?", (VIDEO,)
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(ui, "fetch_public_metadata", lambda _id: (_ for _ in ()).throw(
        RuntimeError("Sign in to confirm you're not a bot")
    ))
    monkeypatch.setattr(ui, "fetch_transcript", lambda _id: (_ for _ in ()).throw(
        AssertionError("No transcript or model calls before original metadata proof")
    ))
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    with pytest.raises(RuntimeError, match="вихідний опис"):
        ui.MainWindow._generate_local_seo_result(state, VIDEO)
    assert not (tmp_path / "seo_evidence").exists()


def test_public_source_merge_rejects_cross_video_and_missing_description():
    from rg_youtube_control.cached_metadata import merge_verified_public_source_metadata
    original = {"title": "TRUSTED CACHED TITLE", "source_description_available": False}
    with pytest.raises(ValueError, match="another video"):
        merge_verified_public_source_metadata(original, VIDEO, {
            "video_id": "ZZZZZZZZZZZ", "description": "FOREIGN SOURCE",
        })
    with pytest.raises(ValueError, match="original description"):
        merge_verified_public_source_metadata(original, VIDEO, {
            "video_id": VIDEO, "title": "UNTRUSTED",
        })


def test_public_metadata_empty_description_does_not_claim_source_verification():
    from rg_youtube_control.cached_metadata import merge_verified_public_source_metadata
    cached = {"title": "TRUSTED", "source_description_available": False}
    for empty in ("", None, "  "):
        with pytest.raises(ValueError, match="original description is empty"):
            merge_verified_public_source_metadata(
                cached, VIDEO, {"video_id": VIDEO, "description": empty}
            )
    assert cached["source_description_available"] is False


def test_owner_source_helper_checks_channel_and_requires_one_request(tmp_path):
    from rg_youtube_control.cached_metadata import recover_original_from_owner_api
    from rg_youtube_control.config import PROFILE_TARGETS
    cached = {
        "title": "TRUSTED", "description": "",
        "source_description_available": False,
        "channel_id": PROFILE_TARGETS["live"],
    }
    class OneRead:
        def __init__(self, *, profile):
            assert profile == "live"
        def credentials(self):
            return object()
        def video_details_with_request_count(self, video_ids):
            assert video_ids == [VIDEO]
            return [{
                "id": VIDEO, "snippet": {
                    "channelId": PROFILE_TARGETS["live"],
                    "description": "Донати: https://donate.rginfoua.pp.ua",
                    "tags": ["чат рулетка"],
                },
            }], 1
    source, count = recover_original_from_owner_api(
        cached, VIDEO, profile="live", client_factory=OneRead
    )
    assert count == 1
    assert source["source"] == "sqlite-plus-owner-readonly"
    assert source["youtube_data_api_quota"] == 1
    assert source["title"] == "TRUSTED"
    assert source["description"].startswith("Донати:")
    assert source["tags"] == ["чат рулетка"]


def test_owner_source_helper_rejects_foreign_channel():
    from rg_youtube_control.cached_metadata import recover_original_from_owner_api
    from rg_youtube_control.config import PROFILE_TARGETS
    cached = {
        "title": "TRUSTED", "description": "",
        "source_description_available": False,
        "channel_id": PROFILE_TARGETS["live"],
    }
    class OtherChannel:
        def __init__(self, *, profile):
            pass
        def credentials(self):
            return object()
        def video_details_with_request_count(self, ids):
            return [{
                "id": VIDEO,
                "snippet": {
                    "channelId": "FOREIGN_CHANNEL",
                    "description": "FOREIGN PRIVATE TEXT",
                },
            }], 1
    with pytest.raises(ValueError, match="does not match"):
        recover_original_from_owner_api(
            cached, VIDEO, profile="live", client_factory=OtherChannel
        )


def test_local_seo_owner_api_fallback_accounts_for_one_read_and_preserves_source(
    monkeypatch, tmp_path,
):
    import rg_youtube_control.ui as ui
    from rg_youtube_control.cached_metadata import merge_verified_public_source_metadata
    from rg_youtube_control.service import today_quota_units
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    conn.execute("DELETE FROM metadata_history WHERE video_id=?", (VIDEO,))
    conn.execute(
        "UPDATE optimization_drafts SET source_description='', source_tags_json='[]' "
        "WHERE video_id=?", (VIDEO,)
    )
    conn.commit()
    before_units = today_quota_units(conn)
    conn.close()
    monkeypatch.setattr(ui, "fetch_public_metadata", lambda _id: (
        _ for _ in ()
    ).throw(RuntimeError("Public extractor unavailable")))
    owner_calls = []
    def owner_source(cached, video_id, *, profile):
        owner_calls.append((video_id, profile))
        source = merge_verified_public_source_metadata(
            cached, video_id, {
                "video_id": video_id,
                "description": "Донати: https://donate.rginfoua.pp.ua",
                "tags": ["чат рулетка"],
            }
        )
        return source, 1
    monkeypatch.setattr(ui, "recover_original_from_owner_api", owner_source)
    monkeypatch.setattr(ui, "fetch_transcript", lambda *_a: [{
        "text": "Поговорим про Перуна и веру в России.",
        "start": 0.0, "duration": 5,
    }])
    monkeypatch.setattr(ui, "analyze_all_timeline_blocks", lambda *_a, **_k: {
        "blocks_total": 1, "blocks_with_evidence": 1,
        "source_integrity_verified": True, "blocks": [{
            "start_stamp": "00:00:00", "topics": [{
                "topic": "Віра в Перуна", "summary_uk": "Розмова про релігію",
                "evidence": "Поговорим про Перуна",
            }],
        }],
    })
    observed = {}
    monkeypatch.setattr(ui, "generate_seo_package_local", lambda **kw: (
        observed.update(kw) or {
            "title": kw["current_title"], "description": "Підтверджений опис",
            "title_variants": [], "tags": [], "needs_review": True,
        }
    ))
    stages = []
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    result = ui.MainWindow._generate_local_seo_result(
        state, VIDEO, on_progress=stages.append
    )
    assert owner_calls == [(VIDEO, "main")]
    assert observed["current_description"].startswith(
        "Донати: https://donate.rginfoua.pp.ua"
    )
    assert result["context"]["source"] == "sqlite-plus-owner-readonly" or (
        result["context"]["source"] == "sqlite-plus-public-source"
    )
    with sqlite3.connect(tmp_path / "rg_youtube_control.db") as verify:
        assert today_quota_units(verify) == before_units + 1
    assert any("1 одиниця API" in message for message in stages)


def test_owner_source_fallback_respects_quota_reserve(monkeypatch, tmp_path):
    import rg_youtube_control.ui as ui
    conn = connect(tmp_path / "rg_youtube_control.db")
    _seed(conn)
    conn.execute("DELETE FROM metadata_history WHERE video_id=?", (VIDEO,))
    conn.execute(
        "UPDATE optimization_drafts SET source_description='', source_tags_json='[]' "
        "WHERE video_id=?", (VIDEO,)
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(ui, "fetch_public_metadata", lambda *_a: (
        _ for _ in ()
    ).throw(RuntimeError("Public metadata unavailable")))
    monkeypatch.setattr(ui, "quota_budget_status", lambda _conn: {
        "exhausted": True, "spendable": 0,
    })
    monkeypatch.setattr(ui, "recover_original_from_owner_api", lambda *_a, **_k: (
        _ for _ in ()
    ).throw(AssertionError("Must not use owner quota over reserve")))
    state = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    with pytest.raises(RuntimeError, match="квоту"):
        ui.MainWindow._generate_local_seo_result(state, VIDEO)
