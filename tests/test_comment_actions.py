from __future__ import annotations

from rg_youtube_control.comment_actions import decide_comment_action
from rg_youtube_control.db import (
    comment_action_counts,
    connect,
    reclassify_comment_actions,
    upsert_comment,
    upsert_video,
)


def _video(conn):
    upsert_video(
        conn,
        {
            "video_id": "v1",
            "profile": "main",
            "channel_id": "channel",
            "title": "Тест",
            "published_at": "2026-10-07T08:00:00Z",
            "privacy_status": "public",
            "views": 1,
            "audit": {},
        },
    )


def test_four_state_rules():
    assert decide_comment_action("Дякую за вашу працю!").action == "reply"
    assert decide_comment_action("Слава Україні!").action == "like"
    assert decide_comment_action("😂😂😂").action == "like"
    assert decide_comment_action("Чому знову черги на заправках?").action == "review"
    assert decide_comment_action("Це просто мій довгий коментар без питання").action == "review"
    assert decide_comment_action("Ти дебіл").action == "skip"


def test_patriotic_thanks_prefers_like():
    decision = decide_comment_action("Дякую ЗСУ! Слава Україні!")
    assert decision.action == "like"
    assert decision.category == "patriotic_support"


def test_info_requests_are_safe_reply():
    assert decide_comment_action("Де посилання?").action == "reply"
    assert decide_comment_action("Де збір?").action == "reply"
    assert decide_comment_action("Коли наступний стрім?").action == "reply"


def test_upsert_persists_comment_action(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _video(conn)
        upsert_comment(
            conn,
            {
                "comment_id": "c1",
                "video_id": "v1",
                "author": "viewer",
                "text": "Слава Україні!",
                "published_at": "2026-10-07T09:00:00Z",
                "status": "new",
                "raw": {},
            },
        )
        row = conn.execute(
            "SELECT action,action_reason,category FROM comments WHERE comment_id='c1'"
        ).fetchone()
        assert row["action"] == "like"
        assert row["category"] == "patriotic_support"
        assert row["action_reason"]
    finally:
        conn.close()


def test_reclassify_marks_duplicate_same_author_text(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _video(conn)
        for cid, published in (
            ("old", "2026-10-07T09:00:00Z"),
            ("new", "2026-10-07T10:00:00Z"),
        ):
            upsert_comment(
                conn,
                {
                    "comment_id": cid,
                    "video_id": "v1",
                    "author": "same viewer",
                    "text": "Дякую за вашу працю!",
                    "published_at": published,
                    "status": "new",
                    "raw": {},
                },
            )

        stats = reclassify_comment_actions(conn)
        newer = conn.execute(
            "SELECT action FROM comments WHERE comment_id='new'"
        ).fetchone()
        older = conn.execute(
            "SELECT action,action_reason,category FROM comments WHERE comment_id='old'"
        ).fetchone()
        assert newer["action"] == "reply"
        assert older["action"] == "skip"
        assert older["action_reason"] == "duplicate_same_author_text"
        assert older["category"] == "duplicate"
        assert stats["reply"] == 1
        assert stats["skip"] == 1
    finally:
        conn.close()


def test_action_counts(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _video(conn)
        examples = [
            ("a", "Дякую!", "new"),
            ("b", "😂", "new"),
            ("c", "Чому так?", "new"),
            ("d", "Ти дебіл", "new"),
        ]
        for cid, text, status in examples:
            upsert_comment(
                conn,
                {
                    "comment_id": cid,
                    "video_id": "v1",
                    "author": cid,
                    "text": text,
                    "published_at": "2026-10-07T10:00:00Z",
                    "status": status,
                    "raw": {},
                },
            )
        counts = comment_action_counts(conn, "main")
        assert counts["reply"] == 1
        assert counts["like"] == 1
        assert counts["review"] == 1
        assert counts["skip"] == 1
    finally:
        conn.close()
