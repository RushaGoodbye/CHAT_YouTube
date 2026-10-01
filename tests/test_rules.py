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