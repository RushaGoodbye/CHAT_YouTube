import json

from rg_youtube_control.db import (
    clear_comment_drafts,
    comment_draft_counts,
    connect,
    save_comment_draft,
    upsert_comment,
    upsert_video,
)
from rg_youtube_control.free_tools import (
    generate_comment_reply_candidate_local,
)


def _seed(conn):
    upsert_video(
        conn,
        {
            "video_id": "v1",
            "profile": "main",
            "channel_id": "ch",
            "title": "Тестове відео",
            "published_at": "2026-10-06T18:00:00Z",
            "scheduled_publish_at": None,
            "privacy_status": "public",
            "duration": "PT10M",
            "views": 10,
            "audit": {},
        },
    )
    for cid, status in (("c1", "new"), ("c2", "new"), ("c3", "moderation_locked")):
        upsert_comment(
            conn,
            {
                "comment_id": cid,
                "video_id": "v1",
                "author": "viewer",
                "text": "Спасибо за эфир!",
                "published_at": "2026-10-06T19:00:00Z",
                "category": "thanks",
                "status": status,
                "reply_text": "",
                "raw": {},
            },
        )


def test_comment_draft_lifecycle(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _seed(conn)
        assert save_comment_draft(
            conn,
            "c1",
            "Дякуємо за підтримку!",
            state="ready",
            reason="relevant",
        )
        assert save_comment_draft(
            conn,
            "c2",
            "",
            state="skipped",
            reason="model_skip",
        )

        counts = comment_draft_counts(conn, "main")
        assert counts["ready"] == 1
        assert counts["skipped"] == 1
        assert counts["moderation_locked"] == 1

        row = conn.execute(
            "SELECT reply_text,draft_state,draft_reason FROM comments WHERE comment_id='c1'"
        ).fetchone()
        assert row["reply_text"] == "Дякуємо за підтримку!"
        assert row["draft_state"] == "ready"
        assert row["draft_reason"] == "relevant"

        cleared = clear_comment_drafts(conn, "main")
        assert cleared == 2
        counts = comment_draft_counts(conn, "main")
        assert counts["ready"] == 0
        assert counts["skipped"] == 0
        assert counts["moderation_locked"] == 1
    finally:
        conn.close()


def test_moderation_locked_comment_cannot_receive_draft(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _seed(conn)
        assert save_comment_draft(
            conn,
            "c3",
            "Не повинно записатися",
            state="ready",
            reason="test",
        ) is False
        row = conn.execute(
            "SELECT reply_text,draft_state FROM comments WHERE comment_id='c3'"
        ).fetchone()
        assert not str(row["reply_text"] or "").strip()
        assert not str(row["draft_state"] or "").strip()
    finally:
        conn.close()


def test_structured_local_reply_ready(monkeypatch):
    def fake_chat(*args, **kwargs):
        return json.dumps(
            {
                "action": "reply",
                "reply": "Дякуємо за підтримку!",
                "reason": "thanks",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(
        "rg_youtube_control.free_tools.ollama_chat",
        fake_chat,
    )
    result = generate_comment_reply_candidate_local(
        comment_text="Спасибо за эфир и работу!",
        video_title="Стрім",
    )
    assert result["state"] == "ready"
    assert result["reply"] == "Дякуємо за підтримку!"


def test_structured_local_reply_skip(monkeypatch):
    def fake_chat(*args, **kwargs):
        return json.dumps(
            {
                "action": "skip",
                "reply": "",
                "reason": "needs_context",
            }
        )

    monkeypatch.setattr(
        "rg_youtube_control.free_tools.ollama_chat",
        fake_chat,
    )
    result = generate_comment_reply_candidate_local(
        comment_text="А что там дальше?",
        video_title="Стрім",
    )
    assert result["state"] == "skipped"
    assert result["reply"] == ""
    assert result["reason"] == "needs_context"


def test_comment_ui_exposes_draft_workflow():
    import inspect
    from rg_youtube_control.ui import MainWindow

    build = inspect.getsource(MainWindow._build_comments_tab)
    assert "Створити x20 · 0 квоти" in build
    assert "Перегенерувати x20 · 0 квоти" in build
    assert "Очистити чернетки" in build
    assert "Стан чернетки" in build
    assert "Пропущені quality-gate" in build
    assert "comment_draft_preview" in build

    reload_source = inspect.getsource(MainWindow.reload_comments)
    assert "draft_state" in reload_source
    assert "comment_draft_counts" in reload_source
    assert "moderation_locked" in reload_source


def test_preview_reads_draft_directly_from_sqlite():
    import inspect
    from rg_youtube_control.ui import MainWindow

    source = inspect.getsource(MainWindow._update_comment_draft_preview)
    assert "SELECT reply_text,draft_state,draft_reason,status" in source
    assert "FROM comments WHERE comment_id=?" in source
