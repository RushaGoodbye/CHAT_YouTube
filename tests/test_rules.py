from rg_youtube_control.comment_rules import classify
from rg_youtube_control.metadata_audit import audit, normalize_links

def test_simple_thanks_is_safe():
    result = classify("Дякую за стрім!")
    assert result.category == "thanks"
    assert result.auto_allowed is True

def test_donate_request_is_safe():
    result = classify("Де реквізити для донату?")
    assert result.category == "donate"
    assert result.auto_allowed is True

def test_political_text_requires_review():
    result = classify("Спасибо, но что вы думаете о войне?")
    assert result.category == "review"
    assert result.auto_allowed is False

def test_unknown_text_requires_review():
    result = classify("Интересный выпуск")
    assert result.category == "review"

def test_old_links_are_replaced():
    source = "https://rg-links-d9e.pages.dev/ https://rg-donates.pages.dev/"
    value = normalize_links(source)
    assert "links.rginfoua.pp.ua" in value
    assert "donate.rginfoua.pp.ua" in value

def test_empty_metadata_needs_work():
    result = audit("", [])
    assert result.needs_update is True
    assert "thin_description" in result.issues
    assert "no_tags" in result.issues

def test_title_script_profile_and_audit_flag_latin_title():
    from rg_youtube_control.metadata_audit import audit, title_script_profile

    assert title_script_profile("Sergey's Identity Crisis: Armenian or Not?") == "latin"
    assert title_script_profile("Доктор-анестезиолог: Моя зарплата в России!") == "cyrillic"

    result = audit(
        "Достатньо довгий опис " * 30,
        ["tag"],
        "Sergey's Identity Crisis: Armenian or Not?",
    )
    assert "latin_title_review" in result.issues


def test_automatic_cyrillic_to_latin_title_change_is_blocked():
    from rg_youtube_control.metadata_audit import (
        blocks_automatic_title_language_change,
    )

    assert blocks_automatic_title_language_change(
        "Доктор-анестезиолог: Моя зарплата в России!",
        "Anesthesiologist: My Salary in Russia!",
    )
    assert not blocks_automatic_title_language_change(
        "Доктор-анестезиолог: Моя зарплата в России!",
        "Доктор-анестезиолог: Сколько платят в России?",
    )
    assert not blocks_automatic_title_language_change(
        "Sergey's Identity Crisis: Armenian or Not?",
        "Сергей: армянин или нет?",
    )


def test_safe_metadata_mode_allows_description_and_tags_only():
    from rg_youtube_control.ui import _validate_safe_update_fields

    _validate_safe_update_fields({"description"})
    _validate_safe_update_fields({"tags"})
    _validate_safe_update_fields({"description", "tags"})

    for fields in (
        {"title"},
        {"description", "title"},
        {"tags", "title"},
        {"privacy_status"},
    ):
        try:
            _validate_safe_update_fields(fields)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"Safe mode accepted forbidden fields: {fields}")


def test_comments_disabled_reason_is_detected():
    import json
    import httplib2
    from googleapiclient.errors import HttpError
    from rg_youtube_control.service import _http_error_reason

    response = httplib2.Response({"status": "403"})
    payload = {
        "error": {
            "code": 403,
            "message": "The video has disabled comments.",
            "errors": [
                {
                    "domain": "youtube.commentThread",
                    "reason": "commentsDisabled",
                    "message": "The video has disabled comments.",
                }
            ],
        }
    }
    exc = HttpError(response, json.dumps(payload).encode("utf-8"))
    assert _http_error_reason(exc) == "commentsDisabled"


def test_auto_reply_respects_age_and_per_scan_limit(tmp_path):
    from datetime import datetime, timedelta, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import scan_comments

    class FakeClient:
        def __init__(self, published_times):
            self.published_times = published_times
            self.sent = []

        def my_channel(self):
            return {"id": "owner"}

        def comment_threads(self, video_id, limit=100):
            items = []
            for index, published in enumerate(self.published_times, start=1):
                items.append({
                    "snippet": {
                        "totalReplyCount": 0,
                        "topLevelComment": {
                            "id": f"c{index}",
                            "snippet": {
                                "authorChannelId": {"value": f"viewer{index}"},
                                "authorDisplayName": f"viewer{index}",
                                "textOriginal": "Спасибо большое!",
                                "publishedAt": published,
                            },
                        },
                    }
                })
            return items

        def replies(self, parent_comment_id):
            return []

        def reply(self, parent_comment_id, text):
            self.sent.append((parent_comment_id, text))
            return {}

    now = datetime.now(timezone.utc)
    recent = now.isoformat().replace("+00:00", "Z")
    old = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")

    conn = connect(tmp_path / "rg.db")
    client = FakeClient([recent, recent, old])
    stats = scan_comments(
        client,
        conn,
        ["video1"],
        auto_reply=True,
        max_auto_replies=20,
        max_auto_replies_per_scan=1,
        max_auto_age_hours=72,
    )

    assert stats["auto_replied"] == 1
    assert len(client.sent) == 1


def test_reply_counters_only_track_app_sent_replies(tmp_path):
    from datetime import datetime, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import (
        manual_reply,
        today_auto_reply_count,
        today_reply_count,
    )

    class FakeClient:
        def reply(self, parent_comment_id, text):
            return {}

    conn = connect(tmp_path / "rg.db")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO comments(
            comment_id,video_id,author,text,published_at,category,status,raw_json
        ) VALUES(?,?,?,?,?,?,?,?)""",
        ("c1", "v1", "viewer", "Спасибо", now, "thanks", "new", "{}"),
    )
    conn.commit()

    manual_reply(FakeClient(), conn, "c1", "Дякуємо!")
    assert today_reply_count(conn) == 1
    assert today_auto_reply_count(conn) == 0


def test_safe_description_fix_adds_only_missing_link():
    from rg_youtube_control.config import DONATE_URL, PROJECT_LINKS_URL
    from rg_youtube_control.optimization import safe_description_fix

    source = f"Опис відео\n\nУСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n{PROJECT_LINKS_URL}"
    fixed = safe_description_fix(source)
    assert fixed.after.count(PROJECT_LINKS_URL) == 1
    assert fixed.after.count(DONATE_URL) == 1
    assert "додано посилання на донат" in fixed.changes


def test_safe_link_issue_detection():
    from rg_youtube_control.optimization import has_safe_link_issue

    assert has_safe_link_issue(["old_links"])
    assert has_safe_link_issue(["missing_project_link", "no_chapters"])
    assert has_safe_link_issue(["missing_donate_link"])
    assert not has_safe_link_issue(["thin_description", "no_tags"])


def test_scheduled_video_has_top_optimization_priority():
    from rg_youtube_control.optimization import priority_label

    scheduled = priority_label(
        100,
        "private",
        "2026-10-10T14:00:00Z",
        [],
    )
    old_links = priority_label(
        15,
        "public",
        None,
        ["old_links"],
    )
    assert scheduled[0] > old_links[0]
    assert scheduled[1] == "ЗАПЛАНОВАНО"


def test_database_migrates_video_columns_and_keeps_history(tmp_path):
    import json
    import sqlite3

    from rg_youtube_control.db import (
        connect,
        latest_metadata_snapshot,
        save_metadata_snapshot,
    )

    db_path = tmp_path / "legacy.sqlite"
    raw = sqlite3.connect(db_path)
    raw.execute(
        """CREATE TABLE videos (
            video_id TEXT PRIMARY KEY,
            channel_id TEXT,
            title TEXT NOT NULL,
            published_at TEXT,
            privacy_status TEXT,
            views INTEGER DEFAULT 0,
            audit_json TEXT DEFAULT '{}',
            last_synced_at TEXT NOT NULL
        )"""
    )
    raw.commit()
    raw.close()

    conn = connect(db_path)
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(videos)").fetchall()
    }
    assert "scheduled_publish_at" in columns
    assert "duration" in columns

    save_metadata_snapshot(
        conn,
        "video1",
        "Old title",
        "Old description",
        ["tag1"],
        "test",
    )
    snapshot = latest_metadata_snapshot(conn, "video1")
    assert snapshot is not None
    assert snapshot["title"] == "Old title"
    assert json.loads(snapshot["tags_json"]) == ["tag1"]


def test_chapter_validation_and_composition():
    from rg_youtube_control.config import PROJECT_LINKS_URL
    from rg_youtube_control.optimization import compose_description, validate_chapters

    chapters = "00:00 Вступ\n00:15 Тема\n00:40 Фінал"
    ok, message = validate_chapters(chapters)
    assert ok, message

    bad, _ = validate_chapters("00:00 Старт\n00:05 Надто рано\n00:20 Далі")
    assert not bad

    invalid_time, _ = validate_chapters(
        "00:00 Старт\n00:75 Невірно\n02:00 Далі"
    )
    assert not invalid_time

    description = (
        "Короткий опис ролика.\n\n"
        "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n"
        f"{PROJECT_LINKS_URL}"
    )
    composed = compose_description(description, chapters)
    assert composed.index("00:00 Вступ") < composed.index(
        "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:"
    )

    duplicated = (
        "Короткий опис ролика.\n\n"
        "00:00 Вступ\n00:15 Тема\n00:40 Фінал\n\n"
        "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n"
        f"{PROJECT_LINKS_URL}"
    )
    cleaned = compose_description(duplicated, chapters)
    assert cleaned.count("00:00 Вступ") == 1
    assert cleaned.count("00:15 Тема") == 1
    assert cleaned.count("00:40 Фінал") == 1


def test_optimization_draft_round_trip(tmp_path):
    import json

    from rg_youtube_control.db import (
        connect,
        get_optimization_draft,
        save_optimization_draft,
        set_optimization_draft_status,
    )

    conn = connect(tmp_path / "draft.sqlite")
    save_optimization_draft(
        conn,
        "video1",
        "Нове название",
        "Опис",
        "00:00 Вступ\n00:20 Далі\n00:40 Фінал",
        ["tag1", "tag2"],
        "draft",
        ["Вариант A", "Вариант B", "Вариант C"],
    )
    draft = get_optimization_draft(conn, "video1")
    assert draft is not None
    assert draft["new_title"] == "Нове название"
    assert json.loads(draft["tags_json"]) == ["tag1", "tag2"]
    assert json.loads(draft["title_variants_json"]) == [
        "Вариант A",
        "Вариант B",
        "Вариант C",
    ]

    set_optimization_draft_status(conn, "video1", "ready")
    ready = get_optimization_draft(conn, "video1")
    assert ready["status"] == "ready"


def test_two_youtube_channels_are_configured():
    from rg_youtube_control.config import LIVE_CHANNEL_ID, MAIN_CHANNEL_ID, PROFILE_TARGETS

    assert PROFILE_TARGETS["main"] == MAIN_CHANNEL_ID
    assert PROFILE_TARGETS["live"] == LIVE_CHANNEL_ID
    assert MAIN_CHANNEL_ID != LIVE_CHANNEL_ID


def test_nas_paths_are_normalized_to_unc():
    from rg_youtube_control.config import (
        DEFAULT_NAS_TRANSCRIPTS_PATH,
        normalize_nas_unc_path,
    )

    assert normalize_nas_unc_path(
        r"\AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL\TRANSCRIPTS",
        DEFAULT_NAS_TRANSCRIPTS_PATH,
    ) == DEFAULT_NAS_TRANSCRIPTS_PATH
    assert normalize_nas_unc_path(
        r"AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL\TRANSCRIPTS",
        DEFAULT_NAS_TRANSCRIPTS_PATH,
    ) == DEFAULT_NAS_TRANSCRIPTS_PATH
    assert normalize_nas_unc_path(
        DEFAULT_NAS_TRANSCRIPTS_PATH,
        DEFAULT_NAS_TRANSCRIPTS_PATH,
    ) == DEFAULT_NAS_TRANSCRIPTS_PATH
    assert normalize_nas_unc_path(
        r"\\\\AlexLosServer\\RG_AUTO_EDIT\\YOUTUBE_CONTROL\\TRANSCRIPTS",
        DEFAULT_NAS_TRANSCRIPTS_PATH,
    ) == DEFAULT_NAS_TRANSCRIPTS_PATH
    assert normalize_nas_unc_path(
        r"\\\\AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL\TRANSCRIPTS",
        DEFAULT_NAS_TRANSCRIPTS_PATH,
    ) == DEFAULT_NAS_TRANSCRIPTS_PATH


def test_update_video_sends_only_writable_snippet_and_verifies_title():
    from rg_youtube_control.youtube_api import YouTubeClient

    calls = {}

    class Request:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class Videos:
        def list(self, **kwargs):
            return Request(
                {
                    "items": [
                        {
                            "snippet": {
                                "title": "Old title",
                                "description": "Old description",
                                "tags": ["one", "two"],
                                "categoryId": "22",
                                "defaultLanguage": "ru",
                                "localized": {"title": "Localized old title"},
                                "channelTitle": "Read only",
                                "publishedAt": "2026-01-01T00:00:00Z",
                            }
                        }
                    ]
                }
            )

        def update(self, **kwargs):
            calls.update(kwargs)
            return Request({"snippet": kwargs["body"]["snippet"]})

    videos = Videos()

    class Client(YouTubeClient):
        def service(self):
            class Service:
                def videos(self):
                    return videos

            return Service()

    client = Client(profile="main")
    result = client.update_video("video-1", title="Нова назва")

    snippet = calls["body"]["snippet"]
    assert snippet["title"] == "Нова назва"
    assert snippet["description"] == "Old description"
    assert snippet["tags"] == ["one", "two"]
    assert snippet["categoryId"] == "22"
    assert snippet["defaultLanguage"] == "ru"
    assert "localized" not in snippet
    assert "channelTitle" not in snippet
    assert "publishedAt" not in snippet
    assert result["snippet"]["title"] == "Нова назва"


def test_update_video_rejects_unconfirmed_title_change():
    from rg_youtube_control.youtube_api import YouTubeClient

    class Request:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class Videos:
        def list(self, **kwargs):
            return Request(
                {
                    "items": [
                        {
                            "snippet": {
                                "title": "Old title",
                                "description": "Description",
                                "categoryId": "22",
                            }
                        }
                    ]
                }
            )

        def update(self, **kwargs):
            return Request(
                {
                    "snippet": {
                        "title": "Old title",
                        "description": "Description",
                        "categoryId": "22",
                    }
                }
            )

    videos = Videos()

    class Client(YouTubeClient):
        def service(self):
            class Service:
                def videos(self):
                    return videos

            return Service()

    client = Client(profile="main")
    try:
        client.update_video("video-1", title="Нова назва")
    except RuntimeError as exc:
        assert "не підтвердив зміну назви" in str(exc)
    else:
        raise AssertionError("Unconfirmed title mutation must fail")


def test_best_caption_track_prefers_language_and_manual_track():
    from rg_youtube_control.youtube_api import YouTubeClient

    client = YouTubeClient(profile="test")
    client.caption_tracks = lambda video_id: [
        {
            "id": "en-manual",
            "snippet": {
                "language": "en",
                "trackKind": "standard",
                "status": "serving",
                "isDraft": False,
                "lastUpdated": "2026-09-01T00:00:00Z",
            },
        },
        {
            "id": "ru-asr",
            "snippet": {
                "language": "ru",
                "trackKind": "ASR",
                "status": "serving",
                "isDraft": False,
                "lastUpdated": "2026-09-03T00:00:00Z",
            },
        },
        {
            "id": "ru-manual",
            "snippet": {
                "language": "ru",
                "trackKind": "standard",
                "status": "serving",
                "isDraft": False,
                "lastUpdated": "2026-09-02T00:00:00Z",
            },
        },
    ]

    best = client.best_caption_track("video1")
    assert best is not None
    assert best["id"] == "ru-manual"


def test_video_profiles_are_isolated(tmp_path):
    from rg_youtube_control.db import connect, upsert_video

    conn = connect(tmp_path / "profiles.sqlite")
    for index in range(9):
        upsert_video(
            conn,
            {
                "video_id": f"main-{index}",
                "profile": "main",
                "channel_id": "channel-main",
                "title": f"Main {index}",
                "audit": {"score": 100, "issues": []},
            },
        )
    for index in range(8):
        upsert_video(
            conn,
            {
                "video_id": f"live-{index}",
                "profile": "live",
                "channel_id": "channel-live",
                "title": f"Live {index}",
                "audit": {"score": 15, "issues": ["old_links"]},
            },
        )

    main_count = conn.execute(
        "SELECT COUNT(*) AS n FROM videos WHERE profile=?",
        ("main",),
    ).fetchone()["n"]
    live_count = conn.execute(
        "SELECT COUNT(*) AS n FROM videos WHERE profile=?",
        ("live",),
    ).fetchone()["n"]

    assert main_count == 9
    assert live_count == 8

def test_updater_manifest_parser(monkeypatch):
    import rg_youtube_control.updater as updater

    monkeypatch.setattr(updater, "__version__", "0.2.7")
    info = updater._from_manifest(
        {
            "version": "0.2.8",
            "installer_name": "RG_YouTube_Control_Setup_0.2.8.exe",
            "installer_url": "https://example.test/setup.exe",
            "checksum_url": "https://example.test/setup.exe.sha256",
            "notes": "test",
        }
    )
    assert info is not None
    assert info.version == "0.2.8"
    assert info.installer_name.endswith(".exe")

    monkeypatch.setattr(updater, "__version__", "0.2.8")
    assert updater._from_manifest(
        {
            "version": "0.2.8",
            "installer_name": "RG_YouTube_Control_Setup_0.2.8.exe",
            "installer_url": "https://example.test/setup.exe",
        }
    ) is None

def test_content_package_preflight_accepts_complete_package():
    from rg_youtube_control.config import DONATE_URL, PROJECT_LINKS_URL
    from rg_youtube_control.optimization import validate_content_package

    description = (
        "Розгорнутий опис випуску з достатньою кількістю тексту для перевірки. "
        "Тут є контекст розмови, основні теми, згадки про співрозмовників і зміст. "
        "Опис спеціально довший за двісті п'ятдесят символів, щоб технічна "
        "перевірка не вважала його надто коротким. Додаємо ще кілька речень.\n\n"
        f"{PROJECT_LINKS_URL}\n{DONATE_URL}"
    )
    check = validate_content_package(
        "Сильна назва відео - без довгого тире",
        description,
        "00:00 Вступ\n00:30 Головна тема\n02:00 Фінал",
        ["тег один", "тег два", "тег три"],
        ["Варіант A", "Варіант B", "Варіант C"],
    )
    assert check.ready is True
    assert not check.errors


def test_content_package_preflight_blocks_youtube_limits():
    from rg_youtube_control.optimization import validate_content_package

    check = validate_content_package(
        "X" * 101,
        "Опис",
        "00:00 Вступ\n00:05 Надто рано\n00:20 Далі",
        ["тег"],
        [],
    )
    assert check.ready is False
    assert any("100" in item for item in check.errors)
    assert any("10 секунд" in item for item in check.errors)
def test_extract_chapters_from_description():
    from rg_youtube_control.optimization import extract_chapters_from_description

    description = """Вступний текст.

0:00 Початок
05:20 Друга тема
12:40 Фінал

Завершення."""
    body, chapters = extract_chapters_from_description(description)
    assert "0:00 Початок" not in body
    assert "Завершення." in body
    assert chapters == "0:00 Початок\n05:20 Друга тема\n12:40 Фінал"
def test_package_bridge_validates_local_endpoint_inputs():
    from rg_youtube_control.package_bridge import _base_url, _video_id

    assert _video_id("GQL6N4jQpI8") == "GQL6N4jQpI8"
    assert _base_url("http://AlexLosServer:8790/") == "http://AlexLosServer:8790"

    try:
        _video_id("../../bad")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid video id must be rejected")

    try:
        _base_url("AlexLosServer:8790")
    except ValueError:
        pass
    else:
        raise AssertionError("Bridge URL without scheme must be rejected")
def test_safe_description_fix_keeps_up_to_five_hashtags_without_title():
    from rg_youtube_control.optimization import safe_description_fix

    value = (
        "Опис відео з #текстом у реченні.\n\n"
        "#one #two #three #four #five"
    )
    fixed = safe_description_fix(value)
    assert "#текстом" in fixed.after
    assert "#one" in fixed.after
    assert "#two" in fixed.after
    assert "#three" in fixed.after
    assert "#four" in fixed.after
    assert "#five" in fixed.after
    assert "залишено не більше 3 хештегів" not in fixed.changes
def test_archive_potential_rewards_reach_and_metadata_gaps():
    from rg_youtube_control.optimization import archive_potential_score

    base = archive_potential_score(
        lifetime_views=100000,
        analytics_views=20000,
        impressions=150000,
        ctr_percent=6.0,
        median_ctr_percent=6.0,
        issues=[],
    )
    opportunity = archive_potential_score(
        lifetime_views=100000,
        analytics_views=20000,
        impressions=150000,
        ctr_percent=2.5,
        median_ctr_percent=6.0,
        issues=["no_chapters", "thin_description"],
    )
    assert 0 <= base <= 100
    assert 0 <= opportunity <= 100
    assert opportunity > base


def test_video_analytics_cache_roundtrip(tmp_path):
    from rg_youtube_control.db import (
        commit_video_analytics,
        connect,
        upsert_video_analytics,
    )

    conn = connect(tmp_path / "test.sqlite3")
    upsert_video_analytics(
        conn,
        video_id="abc123XYZ",
        profile="main",
        period_days=90,
        analytics_views=1234,
        engaged_views=987,
        watch_minutes=543.2,
        avd_seconds=321.0,
        subs_gained=12,
        impressions=45678,
        ctr_percent=4.25,
        start_date="2026-07-05",
        end_date="2026-10-02",
    )
    commit_video_analytics(conn)
    row = conn.execute(
        "SELECT * FROM video_analytics_cache WHERE video_id=?",
        ("abc123XYZ",),
    ).fetchone()
    assert row["analytics_views"] == 1234
    assert row["impressions"] == 45678
    assert abs(row["ctr_percent"] - 4.25) < 0.001

def test_sync_videos_deduplicates_duplicate_video_ids(tmp_path):
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import sync_videos

    class FakeClient:
        profile = "live"

        def recent_videos(self, limit=50):
            base = {
                "id": "same-id",
                "snippet": {
                    "channelId": "channel-live",
                    "title": "Stream",
                    "description": "",
                    "tags": [],
                    "publishedAt": "2026-10-01T00:00:00Z",
                },
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "1"},
                "contentDetails": {"duration": "PT1H"},
            }
            return [base, dict(base)]

    conn = connect(tmp_path / "dedupe.sqlite")
    rows = sync_videos(FakeClient(), conn, limit=1000)
    assert len(rows) == 1
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM videos WHERE profile='live'"
    ).fetchone()["n"]
    assert count == 1


def test_sync_videos_records_exact_read_request_count(tmp_path):
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import sync_videos, today_quota_units

    class FakeClient:
        profile = "main"

        def recent_videos_with_request_count(self, limit=50):
            item = {
                "id": "video-1",
                "snippet": {
                    "channelId": "channel-main",
                    "title": "Тестове відео",
                    "description": "Опис",
                    "tags": [],
                    "publishedAt": "2026-10-01T00:00:00Z",
                },
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "10"},
                "contentDetails": {"duration": "PT10M"},
            }
            return [item], 33

    conn = connect(tmp_path / "sync-quota.sqlite")
    before = today_quota_units(conn)
    rows = sync_videos(FakeClient(), conn, limit=1000)

    assert len(rows) == 1
    assert today_quota_units(conn) == before + 33


def test_sync_specific_videos_records_detail_read_count(tmp_path):
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import sync_specific_videos, today_quota_units

    class FakeClient:
        profile = "main"

        def video_details_with_request_count(self, video_ids):
            item = {
                "id": "video-1",
                "snippet": {
                    "channelId": "channel-main",
                    "title": "Тестове відео",
                    "description": "Опис",
                    "tags": [],
                    "publishedAt": "2026-10-01T00:00:00Z",
                },
                "status": {"privacyStatus": "public"},
                "statistics": {"viewCount": "10"},
                "contentDetails": {"duration": "PT10M"},
            }
            return [item], 1

    conn = connect(tmp_path / "specific-sync-quota.sqlite")
    before = today_quota_units(conn)
    rows = sync_specific_videos(FakeClient(), conn, ["video-1"])

    assert len(rows) == 1
    assert today_quota_units(conn) == before + 1


def test_safe_fix_builds_exactly_one_thematic_hashtag():
    from rg_youtube_control.optimization import safe_description_fix

    source = (
        "Опис відео\n\n"
        "#чатрулетка #рашагудбай #russiagoodbye"
    )
    fixed = safe_description_fix(
        source,
        "С бензином беда: очереди на АЗС и экономика России",
    )
    hashtag_lines = [
        line for line in fixed.after.splitlines() if line.strip().startswith("#")
    ]
    assert len(hashtag_lines) == 1
    tags = hashtag_lines[0].split()
    assert tags == ["#рашагудбай", "#чатрулетка", "#бензин"]
    assert "#экономикароссии" not in tags
    assert "#russiagoodbye" not in tags
    assert "оновлено хештеги" in fixed.changes


def test_audit_allows_five_hashtags():
    from rg_youtube_control.metadata_audit import audit
    from rg_youtube_control.config import DONATE_URL, PROJECT_LINKS_URL

    description = (
        "Достатньо довгий опис відео " * 20
        + f"\n{PROJECT_LINKS_URL}\n{DONATE_URL}\n"
        + "00:00 Старт\n00:20 Тема\n00:40 Фінал\n"
        + "#one #two #three #four #five"
    )
    result = audit(description, ["tag"])
    assert "too_many_hashtags" not in result.issues

def test_hashtag_quality_uses_one_curated_topic_only():
    from rg_youtube_control.optimization import optimized_hashtags
    tags = optimized_hashtags(
        "УНИКАЛЬНИЙ РОЗІГРАШ НА ПІДТРИМКУ ЗСУ ВІД ПРОЄКТУ РАША ГУДБАЙ"
    )
    assert tags == ("#рашагудбай", "#чатрулетка", "#зсу")
    assert "#уникальний" not in tags
    assert "#підтримку" not in tags


def test_hashtag_quality_is_exactly_three():
    from rg_youtube_control.optimization import optimized_hashtags
    tags = optimized_hashtags(
        "Путин война Россия Украина бензин экономика санкции мобилизация"
    )
    assert len(tags) == 3
    assert tags[:2] == ("#рашагудбай", "#чатрулетка")


def test_hashtag_topic_falls_back_to_description():
    from rg_youtube_control.optimization import optimized_hashtags
    tags = optimized_hashtags(
        "Сильный разговор с россиянином",
        "Обсуждаем очереди на АЗС и дефицит бензина.",
    )
    assert tags == ("#рашагудбай", "#чатрулетка", "#бензин")

def test_hashtag_title_fallback_uses_concrete_topic_from_real_title():
    from rg_youtube_control.optimization import optimized_hashtags

    tags = optimized_hashtags(
        "ЧАТ РУЛЕТКА РАША ГУДБАЙ. ВЬЕТНАМ, РЯЗАНЬ и Wildberries"
    )
    assert tags == ("#рашагудбай", "#чатрулетка", "#вьетнам")


def test_hashtag_generic_russia_is_only_a_last_resort():
    from rg_youtube_control.optimization import optimized_hashtags

    tags = optimized_hashtags(
        "ЧАТ РУЛЕТКА РАША ГУДБАЙ. Что происходит в России?"
    )
    assert tags == ("#рашагудбай", "#чатрулетка", "#россия")


def test_hashtag_confidence_handles_english_titles():
    from rg_youtube_control.optimization import optimized_hashtags

    assert optimized_hashtags(
        "My Favorite Anime Character: Sanji from One Piece"
    ) == ("#рашагудбай", "#чатрулетка", "#sanji")

    assert optimized_hashtags(
        "Critique of past Ukrainian presidents' decisions"
    ) == ("#рашагудбай", "#чатрулетка", "#украина")

    assert optimized_hashtags(
        "Sergey's Identity Crisis: Armenian or Not?"
    ) == ("#рашагудбай", "#чатрулетка", "#армения")

    assert optimized_hashtags(
        "Cheburashka's Origin: Found in Oranges!"
    ) == ("#рашагудбай", "#чатрулетка", "#чебурашка")


def test_hashtag_confidence_rejects_generic_verb_title():
    from rg_youtube_control.optimization import optimized_hashtags

    tags = optimized_hashtags(
        "Высказываться сдержанно в великом споре"
    )
    assert tags == ("#рашагудбай", "#чатрулетка", "#россия")


def test_latin_title_review_is_excluded_from_safe_archive():
    from rg_youtube_control.optimization import is_safe_archive_candidate

    assert is_safe_archive_candidate(["old_links"])
    assert is_safe_archive_candidate(["missing_project_link", "no_chapters"])
    assert not is_safe_archive_candidate(
        ["old_links", "latin_title_review"]
    )
    assert not is_safe_archive_candidate(["latin_title_review"])


def test_latin_title_review_gets_dedicated_priority():
    from rg_youtube_control.optimization import priority_label

    priority, label = priority_label(
        85,
        "public",
        None,
        ["latin_title_review", "old_links"],
    )
    assert priority == 900
    assert label == "НАЗВА"


def test_safe_archive_batch_limit_is_twenty():
    from rg_youtube_control.config import DEFAULT_ARCHIVE_SAFE_BATCH_LIMIT

    assert DEFAULT_ARCHIVE_SAFE_BATCH_LIMIT == 20


def test_reconcile_local_video_title_updates_audit_without_api(tmp_path):
    import json
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import reconcile_local_video_title

    conn = connect(tmp_path / "reconcile.sqlite")
    conn.execute(
        """INSERT INTO videos(
            video_id,profile,title,privacy_status,published_at,
            views,audit_json,last_synced_at
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            "v1",
            "main",
            "English title",
            "public",
            "2026-10-01T00:00:00Z",
            1,
            json.dumps(
                {"score": 20, "issues": ["latin_title_review", "no_tags"]},
                ensure_ascii=False,
            ),
            "2026-10-01T00:00:00Z",
        ),
    )
    conn.commit()

    reconcile_local_video_title(
        conn,
        video_id="v1",
        title="Русское название",
        description="",
        tags=[],
    )

    row = conn.execute(
        "SELECT title,audit_json FROM videos WHERE video_id='v1'"
    ).fetchone()
    audit_data = json.loads(row["audit_json"])

    assert row["title"] == "Русское название"
    assert "latin_title_review" not in audit_data["issues"]


def test_reply_template_fields_show_from_start():
    import inspect

    from rg_youtube_control.ui import MainWindow

    source = inspect.getsource(MainWindow._build_settings_tab)
    assert "edit.setCursorPosition(0)" in source

    switch_source = inspect.getsource(MainWindow._activate_profile)
    assert "edit.setCursorPosition(0)" in switch_source


def test_settings_polish_avoids_duplicate_channel_selector_and_wide_spins():
    import inspect

    from rg_youtube_control.ui import MainWindow

    source = inspect.getsource(MainWindow._build_settings_tab)

    assert "self.profile_combo.setVisible(False)" in source
    assert "spin.setMaximumWidth(180)" in source
    assert "comments_columns = QHBoxLayout()" in source
    assert "comments_columns.addLayout(comments_left, 1)" in source
    assert "comments_columns.addLayout(comments_right, 1)" in source


def test_settings_ui_is_split_into_readable_sections():
    import inspect

    from rg_youtube_control.ui import MainWindow

    source = inspect.getsource(MainWindow._build_settings_tab)
    for label in (
        "Коментарі",
        "Архів і квота",
        "Сховища / API",
        "Система",
    ):
        assert label in source
    assert "settings_scroll_page" in source
    assert "settings_card" in source


def test_archive_priority_mode_pauses_and_restores_metadata_autopilot(tmp_path):
    from rg_youtube_control.db import connect, get_setting, set_setting
    from rg_youtube_control.service import (
        archive_priority_enabled,
        set_archive_priority_mode,
    )

    conn = connect(tmp_path / "archive-priority.sqlite")
    set_setting(conn, "safe_metadata_autopilot_main", "1")
    set_setting(conn, "safe_metadata_autopilot_live", "0")

    set_archive_priority_mode(conn, True, ("main", "live"))

    assert archive_priority_enabled(conn)
    assert get_setting(conn, "safe_metadata_autopilot_main", "") == "0"
    assert get_setting(conn, "safe_metadata_autopilot_live", "") == "0"
    assert get_setting(
        conn, "archive_priority_saved_autopilot_main", ""
    ) == "1"
    assert get_setting(
        conn, "archive_priority_saved_autopilot_live", ""
    ) == "0"

    set_archive_priority_mode(conn, False, ("main", "live"))

    assert not archive_priority_enabled(conn)
    assert get_setting(conn, "safe_metadata_autopilot_main", "") == "1"
    assert get_setting(conn, "safe_metadata_autopilot_live", "") == "0"
    assert get_setting(
        conn, "safe_autopilot_last_run_main", ""
    )


def test_archive_priority_enable_is_idempotent(tmp_path):
    from rg_youtube_control.db import connect, get_setting, set_setting
    from rg_youtube_control.service import set_archive_priority_mode

    conn = connect(tmp_path / "archive-priority-idempotent.sqlite")
    set_setting(conn, "safe_metadata_autopilot_main", "1")

    set_archive_priority_mode(conn, True, ("main",))
    set_setting(conn, "safe_metadata_autopilot_main", "0")
    set_archive_priority_mode(conn, True, ("main",))

    assert get_setting(
        conn, "archive_priority_saved_autopilot_main", ""
    ) == "1"


def test_archive_campaign_phase_order():
    from rg_youtube_control.archive_campaign import next_campaign_phase

    stats = {
        "main": {"safe_remaining": 5, "deep_remaining": 10},
        "live": {"safe_remaining": 7, "deep_remaining": 20},
    }
    assert next_campaign_phase(stats) == ("safe", "main")

    stats["main"]["safe_remaining"] = 0
    assert next_campaign_phase(stats) == ("safe", "live")

    stats["live"]["safe_remaining"] = 0
    assert next_campaign_phase(stats) == ("deep", "main")

    stats["main"]["deep_remaining"] = 0
    assert next_campaign_phase(stats) == ("deep", "live")

    stats["live"]["deep_remaining"] = 0
    assert next_campaign_phase(stats) == ("complete", "")


def test_archive_campaign_stats_and_deep_manifest(tmp_path):
    import json

    from rg_youtube_control.archive_campaign import (
        archive_profile_stats,
        export_deep_review_manifest,
    )
    from rg_youtube_control.db import connect, deep_review_state_map

    conn = connect(tmp_path / "campaign.sqlite")
    rows = [
        (
            "safe-1",
            "main",
            "c",
            "Безпечне відео",
            "public",
            100,
            {"score": 70, "issues": ["old_links"]},
        ),
        (
            "deep-1",
            "main",
            "c",
            "Глибоке відео",
            "public",
            200,
            {"score": 55, "issues": ["thin_description", "no_tags"]},
        ),
        (
            "clean-1",
            "main",
            "c",
            "Чисте відео",
            "public",
            50,
            {"score": 100, "issues": []},
        ),
    ]
    for video_id, profile, channel_id, title, privacy, views, audit_data in rows:
        conn.execute(
            """INSERT INTO videos(
                video_id,profile,channel_id,title,published_at,
                scheduled_publish_at,privacy_status,duration,views,
                audit_json,last_synced_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                video_id,
                profile,
                channel_id,
                title,
                "2026-01-01T00:00:00Z",
                None,
                privacy,
                "PT10M",
                views,
                json.dumps(audit_data, ensure_ascii=False),
                "2026-10-03T00:00:00Z",
            ),
        )
    conn.commit()

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "deep-1.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nТест\n",
        encoding="utf-8",
    )

    stats = archive_profile_stats(
        conn,
        "main",
        transcript_dir=transcript_dir,
    )
    assert stats["archive_total"] == 3
    assert stats["safe_remaining"] == 1
    assert stats["deep_remaining"] == 1
    assert stats["transcripts"] == 1

    package_dir = tmp_path / "packages"
    path, exported, total = export_deep_review_manifest(
        conn,
        "main",
        transcript_dir=transcript_dir,
        package_dir=package_dir,
        limit=20,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert exported == 1
    assert total == 1
    assert payload["items"][0]["video_id"] == "deep-1"
    assert payload["items"][0]["transcript_ready"] is True
    assert payload["items"][0]["workflow"]["status"] == "draft"
    assert payload["items"][0]["workflow"]["preview_required"] is True
    assert payload["items"][0]["workflow"]["auto_apply"] is False
    assert deep_review_state_map(conn, "main")["deep-1"] == "queued"


def test_deep_review_state_can_complete_candidate(tmp_path):
    import json

    from rg_youtube_control.archive_campaign import archive_profile_stats
    from rg_youtube_control.db import connect, set_deep_review_state

    conn = connect(tmp_path / "deep-state.sqlite")
    conn.execute(
        """INSERT INTO videos(
            video_id,profile,title,privacy_status,views,audit_json,last_synced_at
        ) VALUES(?,?,?,?,?,?,?)""",
        (
            "v1",
            "live",
            "Тест",
            "public",
            1,
            json.dumps(
                {"score": 50, "issues": ["thin_description"]},
                ensure_ascii=False,
            ),
            "2026-10-03T00:00:00Z",
        ),
    )
    conn.commit()

    before = archive_profile_stats(
        conn,
        "live",
        transcript_dir=tmp_path,
    )
    assert before["deep_remaining"] == 1

    set_deep_review_state(
        conn,
        video_id="v1",
        profile="live",
        status="applied",
        note="reviewed",
    )
    after = archive_profile_stats(
        conn,
        "live",
        transcript_dir=tmp_path,
    )
    assert after["deep_remaining"] == 0
    assert after["applied_packages"] == 1


def test_deep_packages_force_draft_and_full_preview():
    import inspect

    from rg_youtube_control.ui import MainWindow

    save_source = inspect.getsource(MainWindow._save_package_payload)
    apply_source = inspect.getsource(MainWindow.apply_content_package)
    preview_source = inspect.getsource(MainWindow._preview_deep_content_package)

    assert "force_draft" in save_source
    assert "requested_status = \"draft\"" in save_source
    assert "_preview_deep_content_package" in apply_source
    assert "ДО" in preview_source
    assert "ПІСЛЯ" in preview_source
    assert "Thumbnail" in preview_source


def test_archive_campaign_center_controls_both_channels():
    import inspect

    from rg_youtube_control.ui import MainWindow

    source = inspect.getsource(MainWindow.show_archive_campaign_center)
    advance_source = inspect.getsource(MainWindow._advance_archive_campaign)

    assert "Основний канал" not in source or "PROFILE_LABELS" in source
    assert "Запустити зараз" in source
    assert "Відкрити поточний етап" in source
    assert "Готові пакети" in source
    assert "Глибока черга → NAS" not in source
    assert "Імпорт глибоких пакетів" not in source
    assert "run_archive_campaign_step(automatic=False)" in source
    assert "set_archive_priority_mode" in advance_source
    assert "tuple(PROFILE_TARGETS.keys())" in advance_source


def test_deep_transcript_batch_accounts_quota_and_reserve():
    import inspect

    from rg_youtube_control.service import CAPTION_TRANSCRIPT_COST
    from rg_youtube_control.ui import MainWindow

    assert CAPTION_TRANSCRIPT_COST == 250

    source = inspect.getsource(MainWindow._export_transcript_video_to_nas)
    deep_source = inspect.getsource(MainWindow.export_deep_review_transcripts)
    center_source = inspect.getsource(MainWindow.show_archive_campaign_center)

    assert "respect_reserve" in source
    assert "record_quota_units" in source
    assert "CAPTION_TRANSCRIPT_COST" in source
    assert "CAPTION_TRANSCRIPT_COST" in deep_source
    assert "deep-черга, транскрипти та імпорт" in center_source


def test_deep_stage_runs_queue_and_transcripts_without_manual_dialogs():
    import inspect

    from rg_youtube_control.ui import MainWindow

    step_source = inspect.getsource(MainWindow.run_archive_campaign_step)
    queue_source = inspect.getsource(MainWindow.export_deep_review_queue_to_nas)
    transcript_source = inspect.getsource(MainWindow.export_deep_review_transcripts)

    assert "export_deep_review_queue_to_nas(" in step_source
    assert "export_deep_review_transcripts(" in step_source
    assert "confirm=False" in step_source
    assert "notify=not automatic" in step_source
    assert "notify: bool = True" in queue_source
    assert "confirm: bool = True" in transcript_source
    assert "notify: bool = True" in transcript_source
    assert "respect_reserve=True" in transcript_source


def test_daily_archive_capacity_uses_full_safe_budget():
    from rg_youtube_control.service import reserve_safe_daily_batch_capacity

    assert reserve_safe_daily_batch_capacity(7500, 500) == 146
    assert reserve_safe_daily_batch_capacity(728, 500) == 14
    assert reserve_safe_daily_batch_capacity(365, 500) == 7
    assert reserve_safe_daily_batch_capacity(51, 500) == 0


def test_daily_archive_button_and_progress_exist():
    import inspect

    from rg_youtube_control.ui import MainWindow

    build_source = inspect.getsource(MainWindow._build_optimization_tab)
    apply_source = inspect.getsource(MainWindow.apply_next_safe_archive_batch)

    assert "Архів: денний пакет" in build_source
    assert "daily=True" in build_source
    assert "QProgressDialog" in apply_source
    assert "reserve_safe_daily_batch_capacity" in apply_source
    assert "Пріоритет архіву" in apply_source


def test_reserve_safe_batch_capacity_uses_real_item_cost():
    from rg_youtube_control.service import (
        SAFE_METADATA_ITEM_COST,
        reserve_safe_batch_capacity,
    )

    assert SAFE_METADATA_ITEM_COST == 52
    assert reserve_safe_batch_capacity(728, 20, final_refresh_reads=1) == 13
    assert reserve_safe_batch_capacity(729, 20, final_refresh_reads=1) == 14
    assert reserve_safe_batch_capacity(52, 20, final_refresh_reads=1) == 0
    assert reserve_safe_batch_capacity(53, 20, final_refresh_reads=1) == 1


def test_video_update_cost_includes_internal_preread():
    from rg_youtube_control.service import VIDEO_UPDATE_COST

    assert VIDEO_UPDATE_COST == 51


def test_title_review_workflow_methods_exist():
    from rg_youtube_control.ui import MainWindow

    assert hasattr(MainWindow, "export_latin_title_review_to_nas")
    assert hasattr(MainWindow, "preview_title_corrections")
    assert hasattr(MainWindow, "apply_title_corrections")


def test_quota_error_detection():
    from rg_youtube_control.ui import _is_quota_exceeded_error
    assert _is_quota_exceeded_error(Exception("reason: quotaExceeded"))
    assert _is_quota_exceeded_error(Exception("Quota exceeded for quota metric"))
    assert not _is_quota_exceeded_error(Exception("commentsDisabled"))


def test_quota_accounting_is_day_scoped():
    from rg_youtube_control.service import record_quota_units, today_quota_units
    from rg_youtube_control.db import connect
    import tempfile
    from pathlib import Path
    conn = connect(Path(tempfile.mkdtemp()) / "quota.db")
    before = today_quota_units(conn)
    after = record_quota_units(conn, 50)
    assert after == before + 50
    assert today_quota_units(conn) == after

def test_optimization_event_roundtrip():
    from pathlib import Path
    import tempfile
    from rg_youtube_control.db import connect, record_optimization_event, optimization_events
    conn = connect(Path(tempfile.mkdtemp()) / "events.db")
    event_id = record_optimization_event(
        conn, history_id=123, video_id="vid1", profile="main",
        reason="safe_optimization", changed_fields="посилання + хештеги"
    )
    assert event_id > 0
    rows = optimization_events(conn, "main", limit=10)
    assert len(rows) == 1
    assert rows[0]["video_id"] == "vid1"
    assert rows[0]["reason"] == "safe_optimization"

def test_recovery_backup_roundtrip(tmp_path):
    from rg_youtube_control.db import connect, set_setting, get_setting
    from rg_youtube_control.recovery import (
        create_recovery_backup,
        read_recovery_manifest,
        restore_recovery_backup,
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = connect(data_dir / "rg_youtube_control.db")
    set_setting(conn, "probe", "before")

    updates = data_dir / "updates"
    updates.mkdir()
    installer = updates / "RG_YouTube_Control_Setup_0.3.23.exe"
    installer.write_bytes(b"fake-installer")

    backup_root = tmp_path / "nas-backups"
    archive = create_recovery_backup(
        conn=conn,
        data_dir=data_dir,
        backup_root=backup_root,
        version="0.3.23",
    )
    assert archive.is_file()

    manifest = read_recovery_manifest(archive)
    assert manifest["version"] == "0.3.23"
    assert manifest["installer_saved"] is True
    conn.close()

    damaged = connect(data_dir / "rg_youtube_control.db")
    set_setting(damaged, "probe", "after")
    damaged.close()

    restore_recovery_backup(data_dir=data_dir, archive=archive)
    restored = connect(data_dir / "rg_youtube_control.db")
    assert get_setting(restored, "probe", "") == "before"
    restored.close()


def test_database_integrity_cleanup_removes_orphans(tmp_path):
    from rg_youtube_control.db import connect, database_integrity_cleanup

    conn = connect(tmp_path / "health.sqlite")
    conn.execute(
        """INSERT INTO metadata_history(
            video_id,title,description,tags_json,reason,created_at
        ) VALUES(?,?,?,?,?,?)""",
        ("missing-video", "Title", "Description", "[]", "test", "2026-10-02T00:00:00Z"),
    )
    conn.execute(
        """INSERT INTO optimization_drafts(
            video_id,new_title,description,chapters,tags_json,
            title_variants_json,status,updated_at
        ) VALUES(?,?,?,?,?,?,?,?)""",
        ("missing-video", "Title", "Description", "", "[]", "[]", "draft", "2026-10-02T00:00:00Z"),
    )
    conn.commit()

    report = database_integrity_cleanup(conn)
    assert report["integrity"] == "ok"
    assert report["deleted"]["metadata_history"] == 1
    assert report["deleted"]["optimization_drafts"] == 1
    assert conn.execute("SELECT COUNT(*) FROM metadata_history").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM optimization_drafts").fetchone()[0] == 0


def test_manual_reply_blocks_duplicate_send(tmp_path):
    from datetime import datetime, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import manual_reply

    class FakeClient:
        def __init__(self):
            self.sent = 0

        def reply(self, parent_comment_id, text):
            self.sent += 1
            return {}

    conn = connect(tmp_path / "comments.sqlite")
    conn.execute(
        """INSERT INTO comments(
            comment_id,video_id,author,text,published_at,category,status,raw_json
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            "c1",
            "v1",
            "viewer",
            "Дякую",
            datetime.now(timezone.utc).isoformat(),
            "thanks",
            "replied",
            "{}",
        ),
    )
    conn.commit()

    client = FakeClient()
    try:
        manual_reply(client, conn, "c1", "Дякуємо!")
    except RuntimeError as exc:
        assert "вже" in str(exc)
    else:
        raise AssertionError("Duplicate reply must be blocked")
    assert client.sent == 0


def test_reply_text_validation():
    from rg_youtube_control.service import _validated_reply_text

    assert _validated_reply_text("  Дякуємо!  ") == "Дякуємо!"
    try:
        _validated_reply_text("   ")
    except ValueError:
        pass
    else:
        raise AssertionError("Empty reply must be blocked")


def test_embedded_replies_avoid_extra_api_call():
    from rg_youtube_control.service import _own_reply_exists

    class FakeClient:
        def __init__(self):
            self.calls = 0
        def replies(self, parent_comment_id):
            self.calls += 1
            return []

    thread = {
        "snippet": {
            "totalReplyCount": 1,
            "topLevelComment": {"id": "c1"},
        },
        "replies": {
            "comments": [{
                "snippet": {
                    "authorChannelId": {"value": "viewer"}
                }
            }]
        },
    }
    client = FakeClient()
    assert _own_reply_exists(client, thread, "owner") is False
    assert client.calls == 0


def test_known_replied_comment_skips_remote_reply_lookup(tmp_path):
    from datetime import datetime, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import scan_comments

    class FakeClient:
        profile = "test"
        def __init__(self):
            self.reply_checks = 0
            self.channel_calls = 0
        def my_channel(self):
            self.channel_calls += 1
            return {"id": "owner"}
        def comment_threads(self, video_id, limit=100):
            return [{
                "snippet": {
                    "totalReplyCount": 1,
                    "topLevelComment": {
                        "id": "known1",
                        "snippet": {
                            "authorChannelId": {"value": "viewer"},
                            "authorDisplayName": "viewer",
                            "textOriginal": "Спасибо!",
                            "publishedAt": datetime.now(timezone.utc).isoformat(),
                        },
                    },
                },
            }]
        def replies(self, parent_comment_id):
            self.reply_checks += 1
            return []

    conn = connect(tmp_path / "rg.db")
    conn.execute(
        """INSERT INTO comments(
            comment_id,video_id,author,text,published_at,category,status,raw_json
        ) VALUES(?,?,?,?,?,?,?,?)""",
        ("known1", "video1", "viewer", "Спасибо!", datetime.now(timezone.utc).isoformat(), "thanks", "replied", "{}"),
    )
    conn.commit()

    client = FakeClient()
    scan_comments(client, conn, ["video1"])
    scan_comments(client, conn, ["video1"])

    assert client.reply_checks == 0
    assert client.channel_calls == 1


def test_quota_budget_keeps_reserve(tmp_path):
    from rg_youtube_control.db import connect, set_setting
    from rg_youtube_control.service import (
        quota_budget_status,
        record_quota_units,
    )

    conn = connect(tmp_path / "quota_budget.sqlite")
    set_setting(conn, "youtube_quota_reserve_units", "2500")
    record_quota_units(conn, 1000)
    budget = quota_budget_status(conn)

    assert budget["remaining"] == 9000
    assert budget["reserve"] == 2500
    assert budget["spendable"] == 6500
    assert budget["reply_capacity"] == 180
    assert budget["campaign_spendable"] == 6500
    assert budget["comment_spendable"] == 9000
    assert budget["campaign_video_capacity"] == 127
    assert budget["campaign_blocked"] is False


def test_action_log_roundtrip(tmp_path):
    from rg_youtube_control.db import connect, log_action, recent_action_log

    conn = connect(tmp_path / "journal.sqlite")
    log_action(
        conn,
        profile="main",
        category="коментарі",
        action="Тест",
        details="деталі",
    )
    rows = recent_action_log(conn, profile="main", limit=10)
    assert len(rows) == 1
    assert rows[0]["category"] == "коментарі"
    assert rows[0]["action"] == "Тест"


def test_incremental_channel_scan_replies_once(tmp_path):
    from datetime import datetime, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import scan_channel_comments

    class FakeClient:
        profile = "main"

        def __init__(self):
            self.sent = []
            self.remote_reply_checks = 0

        def channel_comment_threads(
            self, channel_id, *, stop_before=None, max_pages=5,
            moderation_status="published"
        ):
            return ([{
                "snippet": {
                    "videoId": "video1",
                    "totalReplyCount": 0,
                    "topLevelComment": {
                        "id": "new-comment",
                        "snippet": {
                            "authorChannelId": {"value": "viewer"},
                            "authorDisplayName": "viewer",
                            "textOriginal": "Спасибо большое!",
                            "publishedAt": datetime.now(timezone.utc).isoformat(),
                        },
                    },
                },
            }], 1)

        def replies(self, parent_comment_id):
            self.remote_reply_checks += 1
            return []

        def reply(self, parent_comment_id, text):
            self.sent.append((parent_comment_id, text))
            return {}

    conn = connect(tmp_path / "incremental.sqlite")
    client = FakeClient()

    first = scan_channel_comments(
        client,
        conn,
        "owner",
        auto_reply=True,
        max_auto_replies=30,
        max_auto_replies_per_scan=5,
        max_auto_age_hours=24,
    )
    second = scan_channel_comments(
        client,
        conn,
        "owner",
        auto_reply=True,
        max_auto_replies=30,
        max_auto_replies_per_scan=5,
        max_auto_age_hours=24,
    )

    assert first["auto_replied"] == 1
    assert second["auto_replied"] == 0
    assert second["known_skipped"] == 1
    assert len(client.sent) == 1
    assert client.remote_reply_checks == 0


def test_result_summary_uses_multiple_metrics():
    from rg_youtube_control.ui import MainWindow

    before = {
        "views": 100,
        "watch_minutes": 500,
        "avd_seconds": 120,
        "subs": 4,
    }
    after = {
        "views": 130,
        "watch_minutes": 620,
        "avd_seconds": 125,
        "subs": 5,
    }
    reach_before = {"impressions": 1000, "ctr": 4.0}
    reach_after = {"impressions": 1200, "ctr": 4.4}

    label, key, detail = MainWindow._result_summary(
        before, after, reach_before, reach_after
    )
    assert key == "improved"
    assert label.startswith("Краще:")
    assert "перегляди" in detail
    assert "CTR" in detail


def test_automatic_backup_can_omit_installer_and_prune(tmp_path):
    import os
    from rg_youtube_control.db import connect
    from rg_youtube_control.recovery import (
        create_recovery_backup,
        prune_recovery_backups,
        read_recovery_manifest,
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = connect(data_dir / "rg_youtube_control.db")
    backup_root = tmp_path / "backups"

    archive = create_recovery_backup(
        conn=conn,
        data_dir=data_dir,
        backup_root=backup_root,
        version="9.9.9",
        include_installer=False,
        label="RG_YOUTUBE_CONTROL_AUTO",
    )
    manifest = read_recovery_manifest(archive)
    assert manifest["installer_saved"] is False
    assert archive.is_file()

    for index in range(4):
        folder = backup_root / f"RG_YOUTUBE_CONTROL_AUTO_dummy_{index}"
        folder.mkdir()
        os.utime(folder, (100 + index, 100 + index))

    removed = prune_recovery_backups(
        backup_root,
        keep=2,
        prefix="RG_YOUTUBE_CONTROL_AUTO_",
    )
    assert removed >= 3
    remaining = [
        path for path in backup_root.iterdir()
        if path.is_dir() and path.name.startswith("RG_YOUTUBE_CONTROL_AUTO_")
    ]
    assert len(remaining) == 2


def test_current_quota_day_is_iso_date():
    from datetime import date
    from rg_youtube_control.service import current_quota_day

    parsed = date.fromisoformat(current_quota_day())
    assert isinstance(parsed, date)


def test_reply_test_uses_fresh_safe_local_queue(tmp_path):
    from datetime import datetime, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import reply_one_queued_safe_comment

    class FakeClient:
        profile = "main"

        def __init__(self):
            self.sent = []

        def my_channel(self):
            return {"id": "channel-1"}

        def channel_comment_threads(self, channel_id, *, stop_before=None, max_pages=5):
            return (
                [
                    {
                        "snippet": {
                            "topLevelComment": {
                                "id": "c-safe",
                                "snippet": {},
                            }
                        }
                    }
                ],
                1,
            )

        def reply(self, parent_comment_id, text):
            self.sent.append((parent_comment_id, text))
            return {}

    conn = connect(tmp_path / "queued-reply.sqlite")
    conn.execute(
        """INSERT INTO videos(
            video_id,profile,title,privacy_status,published_at,
            views,audit_json,last_synced_at
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            "v1", "main", "Video", "public",
            datetime.now(timezone.utc).isoformat(), 1, "{}",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.execute(
        """INSERT INTO comments(
            comment_id,video_id,author,text,published_at,category,status,reply_text,raw_json
        ) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            "c-safe", "v1", "viewer", "Дякую!",
            datetime.now(timezone.utc).isoformat(),
            "thanks", "new", "Дякуємо за підтримку! 💙💛", "{}",
        ),
    )
    conn.commit()

    client = FakeClient()
    result = reply_one_queued_safe_comment(
        client,
        conn,
        "main",
        max_auto_age_hours=24,
        max_auto_replies=30,
    )

    assert result["sent"] == 1
    assert client.sent == [("c-safe", "Дякуємо за підтримку! 💙💛")]
    status = conn.execute(
        "SELECT status FROM comments WHERE comment_id='c-safe'"
    ).fetchone()["status"]
    assert status == "replied"


def test_reply_test_blocks_comment_not_reconfirmed_as_published(tmp_path):
    from datetime import datetime, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import reply_one_queued_safe_comment

    class FakeClient:
        profile = "main"

        def my_channel(self):
            return {"id": "channel-1"}

        def channel_comment_threads(self, channel_id, *, stop_before=None, max_pages=5):
            return ([], 1)

        def reply(self, parent_comment_id, text):
            raise AssertionError("Non-published comment must never be answered")

    conn = connect(tmp_path / "queued-moderation-lock.sqlite")
    conn.execute(
        """INSERT INTO videos(
            video_id,profile,title,privacy_status,published_at,
            views,audit_json,last_synced_at
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            "v1", "main", "Video", "public",
            datetime.now(timezone.utc).isoformat(), 1, "{}",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.execute(
        """INSERT INTO comments(
            comment_id,video_id,author,text,published_at,category,status,reply_text,raw_json
        ) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            "c-held", "v1", "viewer", "Дякую!",
            datetime.now(timezone.utc).isoformat(),
            "thanks", "new", "Дякуємо!", "{}",
        ),
    )
    conn.commit()

    result = reply_one_queued_safe_comment(
        FakeClient(), conn, "main", max_auto_age_hours=24
    )

    assert result["sent"] == 0
    assert result["moderation_blocked"] == 1
    status = conn.execute(
        "SELECT status FROM comments WHERE comment_id='c-held'"
    ).fetchone()["status"]
    assert status == "moderation_locked"


def test_reply_test_ignores_old_safe_local_comment(tmp_path):
    from datetime import datetime, timedelta, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import reply_one_queued_safe_comment

    class FakeClient:
        profile = "main"
        def reply(self, parent_comment_id, text):
            raise AssertionError("Old comment must not be answered")

    conn = connect(tmp_path / "queued-old.sqlite")
    conn.execute(
        """INSERT INTO videos(
            video_id,profile,title,privacy_status,published_at,
            views,audit_json,last_synced_at
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            "v1", "main", "Video", "public",
            datetime.now(timezone.utc).isoformat(), 1, "{}",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.execute(
        """INSERT INTO comments(
            comment_id,video_id,author,text,published_at,category,status,reply_text,raw_json
        ) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            "c-old", "v1", "viewer", "Дякую!",
            (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
            "thanks", "new", "Дякуємо!", "{}",
        ),
    )
    conn.commit()

    result = reply_one_queued_safe_comment(
        FakeClient(), conn, "main", max_auto_age_hours=24
    )
    assert result["sent"] == 0


def test_comment_threads_are_hard_locked_to_published():
    from rg_youtube_control.youtube_api import YouTubeClient

    calls = []

    class Request:
        def execute(self):
            return {"items": []}

    class CommentThreads:
        def list(self, **kwargs):
            calls.append(kwargs)
            return Request()

    class Service:
        def commentThreads(self):
            return CommentThreads()

    class Client(YouTubeClient):
        def service(self):
            return Service()

    client = Client(profile="main")
    client.channel_comment_threads("channel-1", max_pages=1)
    client.comment_threads("video-1", limit=1)

    assert len(calls) == 2
    assert calls[0]["moderationStatus"] == "published"
    assert calls[1]["moderationStatus"] == "published"


def test_comment_moderation_mutation_is_disabled():
    from rg_youtube_control.youtube_api import YouTubeClient

    class Client(YouTubeClient):
        def service(self):
            raise AssertionError("Moderation API must never be called")

    client = Client(profile="main")
    try:
        client.set_moderation("comment-1", "published")
    except RuntimeError as exc:
        assert "не змінює статус модерації" in str(exc)
    else:
        raise AssertionError("Moderation mutation must be blocked")


def test_manual_reply_is_profile_counted_and_journaled(tmp_path):
    from datetime import datetime, timezone
    from rg_youtube_control.db import connect, recent_action_log
    from rg_youtube_control.service import manual_reply, today_reply_count

    class FakeClient:
        profile = "live"
        def __init__(self):
            self.sent = []
        def reply(self, comment_id, text):
            self.sent.append((comment_id, text))
            return {}

    conn = connect(tmp_path / "manual-reply-log.sqlite")
    conn.execute(
        """INSERT INTO videos(
            video_id,profile,title,privacy_status,published_at,
            views,audit_json,last_synced_at
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            "v-live", "live", "Video", "public",
            datetime.now(timezone.utc).isoformat(), 1, "{}",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.execute(
        """INSERT INTO comments(
            comment_id,video_id,author,text,published_at,
            category,status,reply_text,raw_json
        ) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            "c-manual", "v-live", "viewer", "Привіт",
            datetime.now(timezone.utc).isoformat(),
            "review", "new", "", "{}",
        ),
    )
    conn.commit()

    client = FakeClient()
    manual_reply(client, conn, "c-manual", "Дякую!")

    assert client.sent == [("c-manual", "Дякую!")]
    assert today_reply_count(conn, "live") == 1
    rows = recent_action_log(conn, profile="live", limit=10)
    assert any(
        row["action"] == "Ручна відповідь"
        and "c-manual" in row["details"]
        for row in rows
    )


def test_autopilot_guardrail_defaults():
    from rg_youtube_control.config import (
        DEFAULT_SAFE_AUTOPILOT_DAILY_LIMIT,
        DEFAULT_SAFE_AUTOPILOT_INTERVAL_MINUTES,
    )

    assert DEFAULT_SAFE_AUTOPILOT_INTERVAL_MINUTES == 60
    assert DEFAULT_SAFE_AUTOPILOT_DAILY_LIMIT == 30

def test_explicit_nonpublished_comment_never_auto_replies(tmp_path):
    from datetime import datetime, timezone
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import scan_channel_comments

    class FakeClient:
        profile = "main"

        def channel_comment_threads(self, channel_id, *, stop_before=None, max_pages=5):
            return ([
                {
                    "snippet": {
                        "videoId": "v-held",
                        "topLevelComment": {
                            "id": "c-held-explicit",
                            "snippet": {
                                "moderationStatus": "heldForReview",
                                "authorDisplayName": "viewer",
                                "authorChannelId": {"value": "viewer-channel"},
                                "textOriginal": "Дякую!",
                                "publishedAt": datetime.now(timezone.utc).isoformat(),
                            },
                        },
                        "totalReplyCount": 0,
                    }
                }
            ], 1)

        def reply(self, parent_comment_id, text):
            raise AssertionError("heldForReview comment must never be answered")

    conn = connect(tmp_path / "held-explicit.sqlite")
    result = scan_channel_comments(
        FakeClient(),
        conn,
        "owner-channel",
        auto_reply=True,
    )
    assert result["auto_replied"] == 0
    assert result["skipped_review"] == 1
    row = conn.execute(
        "SELECT status,category FROM comments WHERE comment_id=?",
        ("c-held-explicit",),
    ).fetchone()
    assert row["status"] == "moderation_locked"
    assert row["category"] == "review"


def test_manual_reply_refuses_moderation_locked_comment(tmp_path):
    from datetime import datetime, timezone
    import pytest
    from rg_youtube_control.db import connect
    from rg_youtube_control.service import manual_reply

    class FakeClient:
        def reply(self, parent_comment_id, text):
            raise AssertionError("moderation-locked comment must not be answered")

    conn = connect(tmp_path / "manual-held.sqlite")
    conn.execute(
        """INSERT INTO comments(
            comment_id,video_id,author,text,published_at,category,status,raw_json
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            "c-locked", "v1", "viewer", "Дякую!",
            datetime.now(timezone.utc).isoformat(),
            "review", "moderation_locked", "{}",
        ),
    )
    conn.commit()
    with pytest.raises(RuntimeError, match="модерації YouTube"):
        manual_reply(FakeClient(), conn, "c-locked", "Відповідь")


def test_comment_reserve_remains_available_when_campaign_is_blocked(tmp_path):
    from rg_youtube_control.db import connect, set_setting
    from rg_youtube_control.service import (
        quota_budget_status,
        record_quota_units,
        SAFE_METADATA_ITEM_COST,
    )

    conn = connect(tmp_path / "reserve-split.sqlite")
    set_setting(conn, "youtube_quota_reserve_units", "2500")
    record_quota_units(conn, 7477)
    budget = quota_budget_status(conn)

    assert budget["remaining"] == 2523
    assert budget["campaign_spendable"] == 23
    assert budget["comment_spendable"] == 2523
    assert budget["campaign_blocked"] is True
    assert budget["campaign_spendable"] < SAFE_METADATA_ITEM_COST
    assert budget["reply_capacity"] >= 50


def test_campaign_checkpoint_recovers_running_stage(tmp_path):
    from rg_youtube_control.archive_campaign import (
        load_campaign_checkpoint,
        reconcile_campaign_checkpoint,
        save_campaign_checkpoint,
    )
    from rg_youtube_control.db import connect

    conn = connect(tmp_path / "checkpoint.sqlite")
    save_campaign_checkpoint(
        conn,
        phase="safe",
        target="main",
        status="running",
        note="simulated_crash",
    )
    stats = {
        "main": {"safe_remaining": 4, "deep_remaining": 7},
        "live": {"safe_remaining": 2, "deep_remaining": 9},
    }
    checkpoint, interrupted = reconcile_campaign_checkpoint(conn, stats)

    assert interrupted is True
    assert checkpoint["phase"] == "safe"
    assert checkpoint["target"] == "main"
    assert checkpoint["status"] == "ready"
    assert checkpoint["note"] == "recovered_after_interruption"
    assert load_campaign_checkpoint(conn)["status"] == "ready"


def test_deep_manifest_write_failure_does_not_queue_state(tmp_path):
    import json
    import pytest
    from rg_youtube_control.archive_campaign import export_deep_review_manifest
    from rg_youtube_control.db import connect, deep_review_state_map

    conn = connect(tmp_path / "deep-nas-failure.sqlite")
    conn.execute(
        """INSERT INTO videos(
            video_id,profile,title,privacy_status,views,audit_json,last_synced_at
        ) VALUES(?,?,?,?,?,?,?)""",
        (
            "deep-fail",
            "main",
            "Тест",
            "public",
            10,
            json.dumps({"score": 50, "issues": ["thin_description"]}),
            "2026-10-03T00:00:00Z",
        ),
    )
    conn.commit()

    package_file = tmp_path / "not-a-directory"
    package_file.write_text("occupied", encoding="utf-8")

    with pytest.raises((OSError, FileExistsError, NotADirectoryError)):
        export_deep_review_manifest(
            conn,
            "main",
            transcript_dir=tmp_path / "missing-transcripts",
            package_dir=package_file,
            limit=20,
        )

    assert deep_review_state_map(conn, "main").get("deep-fail") is None


def test_unavailable_transcript_storage_does_not_break_campaign_stats(tmp_path):
    import json
    from rg_youtube_control.archive_campaign import archive_profile_stats
    from rg_youtube_control.db import connect

    conn = connect(tmp_path / "stats-storage.sqlite")
    conn.execute(
        """INSERT INTO videos(
            video_id,profile,title,privacy_status,views,audit_json,last_synced_at
        ) VALUES(?,?,?,?,?,?,?)""",
        (
            "deep-storage",
            "main",
            "Тест",
            "public",
            10,
            json.dumps({"score": 50, "issues": ["thin_description"]}),
            "2026-10-03T00:00:00Z",
        ),
    )
    conn.commit()
    occupied = tmp_path / "occupied"
    occupied.write_text("x", encoding="utf-8")

    stats = archive_profile_stats(
        conn,
        "main",
        transcript_dir=occupied,
    )
    assert stats["deep_remaining"] == 1
    assert stats["transcripts"] == 0


def test_cached_update_cleanup_keeps_latest_three(tmp_path):
    from rg_youtube_control.updater import prune_cached_updates

    versions = ["0.3.55", "0.3.56", "0.3.57", "0.3.58", "0.3.59"]
    for version in versions:
        (tmp_path / f"RG_YouTube_Control_Setup_{version}.exe").write_bytes(b"x")
        (tmp_path / f"RG_YouTube_Control_Setup_{version}.exe.sha256").write_text(
            "hash", encoding="utf-8"
        )

    removed = prune_cached_updates(tmp_path, keep=3)
    remaining = sorted(path.name for path in tmp_path.iterdir())

    assert len(removed) == 4
    assert all("0.3.55" not in name for name in remaining)
    assert all("0.3.56" not in name for name in remaining)
    assert any("0.3.57" in name for name in remaining)
    assert any("0.3.58" in name for name in remaining)
    assert any("0.3.59" in name for name in remaining)


def test_archive_autorun_is_quota_day_guarded_and_silent():
    import inspect
    from rg_youtube_control.ui import MainWindow

    source = inspect.getsource(MainWindow._run_archive_campaign_autorun)
    step_source = inspect.getsource(MainWindow.run_archive_campaign_step)
    batch_source = inspect.getsource(MainWindow.apply_next_safe_archive_batch)

    assert "archive_campaign_autorun_done_" in source
    assert 'get_setting(\n            self.conn,\n            "archive_campaign_autorun",\n            "1",' in source
    assert 'budget["current_capacity"]' in source
    assert "paused_quota" in source
    assert "run_archive_campaign_step(automatic=True)" in source
    assert "confirm=not automatic" in step_source
    assert "notify=not automatic" in step_source
    assert "respect_reserve=True" in batch_source


def test_archive_autorun_prioritizes_scheduled_before_safe_archive():
    import inspect
    from rg_youtube_control.ui import MainWindow

    autorun = inspect.getsource(MainWindow._run_archive_campaign_autorun)
    helper = inspect.getsource(
        MainWindow._apply_scheduled_before_archive_for_quota_day
    )

    assert "_apply_scheduled_before_archive_for_quota_day" in autorun
    assert "apply_ready_scheduled_packages" in helper
    assert "confirm=False" in helper
    assert "notify=False" in helper
    assert "ready_after > 0" in helper
    assert "архівний бюджет не витрачаємо" in helper


def test_windows_installer_version_comes_from_project_version():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    installer = (root / "packaging" / "installer.iss").read_text(
        encoding="utf-8"
    )
    workflow = (
        root / ".github" / "workflows" / "windows-build.yml"
    ).read_text(encoding="utf-8")

    assert "#ifndef MyAppVersion" in installer
    assert '#define MyAppVersion "0.0.0"' in installer
    assert '#define MyAppVersion "0.3.' not in installer
    assert '"/DMyAppVersion=$version"' in workflow


def test_archive_center_is_compact():
    import inspect
    from rg_youtube_control.ui import MainWindow

    source = inspect.getsource(MainWindow.show_archive_campaign_center)
    assert "QTableWidget(2, 5)" in source
    assert "Готові пакети" in source
    assert "Запустити зараз" in source
    assert "Відкрити поточний етап" in source
    assert "Глибока черга → NAS" not in source
    assert "Імпорт глибоких пакетів" not in source



def test_scheduled_package_apply_has_quota_guard_and_automation_mode():
    import inspect
    from rg_youtube_control.ui import MainWindow

    source = inspect.getsource(MainWindow.apply_ready_scheduled_packages)
    assert "batch_limit = reserve_safe_batch_capacity" in source
    assert "respect_reserve=True" in source
    assert "confirm: bool = True" in source
    assert "notify: bool = True" in source
    assert "SAFE_METADATA_ITEM_COST" in source
    assert "return len(changed_ids)" in source


def test_local_and_scheduled_paths_use_imported_description_sanitizer():
    import inspect
    from rg_youtube_control.ui import MainWindow

    local_source = inspect.getsource(MainWindow._save_local_seo_result)
    scheduled_source = inspect.getsource(MainWindow._prepare_scheduled_package)

    assert "sanitize_imported_package_description" in local_source
    assert "sanitize_imported_package_description" in scheduled_source


def test_imported_package_removes_explicit_english_duplicate():
    import re
    from rg_youtube_control.optimization import (
        sanitize_imported_package_description,
        validate_content_package,
    )

    ukrainian = (
        "Це український опис реальної розмови у чат-рулетці. "
        "Тут збережено контекст відео без вигадування фактів. "
    ) * 8
    english = (
        "The English summary duplicates the same video context and should "
        "not remain in the imported package. "
    ) * 15
    source = (
        ukrainian
        + "\n\n🇬🇧 ENGLISH SUMMARY:\n"
        + english
        + "\n\n#чатрулетка #рашагудбай #росія #україна #відео #стрім #новини\n\n"
        + "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n"
        + "https://links.rginfoua.pp.ua/\n\n"
        + "УСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:\n"
        + "https://donate.rginfoua.pp.ua/"
    )

    fixed = sanitize_imported_package_description(
        source,
        "Розмова з росіянином про бензин",
    )

    assert "🇬🇧 ENGLISH SUMMARY:" not in fixed.after
    assert "The English summary duplicates" not in fixed.after
    assert "https://links.rginfoua.pp.ua/" in fixed.after
    assert "https://donate.rginfoua.pp.ua/" in fixed.after
    hashtags = re.findall(
        r"(?<!\w)#[\wА-Яа-яІіЇїЄєҐґ]+",
        fixed.after,
    )
    assert len(hashtags) == 3

    check = validate_content_package(
        "Розмова з росіянином про бензин",
        fixed.after,
        "",
        ["РАША ГУДБАЙ", "чат рулетка", "Россия", "Украина", "бензин", "АЗС"],
        [],
    )
    assert check.ready is True


def test_imported_package_removes_english_duplicate_without_flag():
    from rg_youtube_control.optimization import sanitize_imported_package_description

    ukrainian = (
        "Український опис з достатнім контекстом для безпечного очищення. "
    ) * 10
    source = (
        ukrainian
        + "\n\nENGLISH SUMMARY:\n"
        + ("This is duplicated English text. " * 30)
        + "\n\n#чатрулетка #рашагудбай #росія"
    )
    fixed = sanitize_imported_package_description(source, "Тестове відео")

    assert "ENGLISH SUMMARY:" not in fixed.after
    assert "This is duplicated English text." not in fixed.after


def test_imported_package_does_not_remove_only_english_body():
    from rg_youtube_control.optimization import (
        sanitize_imported_package_description,
    )

    source = (
        "🇬🇧 ENGLISH SUMMARY:\n"
        "The only meaningful description is English and there is no "
        "substantial Ukrainian body before the marker."
    )
    fixed = sanitize_imported_package_description(source, "Тест")
    assert fixed.after == source
    assert fixed.changes == ()
