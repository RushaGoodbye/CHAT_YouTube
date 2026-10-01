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