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
                "reply": "Так, це справді помітно.",
                "reason": "clear_question",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(
        "rg_youtube_control.free_tools.ollama_chat",
        fake_chat,
    )
    result = generate_comment_reply_candidate_local(
        comment_text="Почему снова такие очереди на заправках?",
        video_title="Стрім",
    )
    assert result["state"] == "ready"
    assert result["reply"] == "Так, це справді помітно."


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


def test_upsert_updates_existing_comment_to_moderation_locked(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _seed(conn)
        upsert_comment(
            conn,
            {
                "comment_id": "c1",
                "video_id": "v1",
                "author": "viewer",
                "text": "Спасибо за эфир!",
                "published_at": "2026-10-06T19:00:00Z",
                "category": "review",
                "status": "moderation_locked",
                "reply_text": "",
                "raw": {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {"moderationStatus": "heldForReview"}
                        }
                    }
                },
            },
        )
        row = conn.execute(
            "SELECT status FROM comments WHERE comment_id='c1'"
        ).fetchone()
        assert row["status"] == "moderation_locked"
    finally:
        conn.close()


def test_upsert_does_not_downgrade_replied_or_ignored(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _seed(conn)
        conn.execute("UPDATE comments SET status='replied' WHERE comment_id='c1'")
        conn.execute("UPDATE comments SET status='ignored' WHERE comment_id='c2'")
        conn.commit()
        for cid in ("c1", "c2"):
            upsert_comment(
                conn,
                {
                    "comment_id": cid,
                    "video_id": "v1",
                    "author": "viewer",
                    "text": "sync",
                    "published_at": "2026-10-06T19:00:00Z",
                    "category": "review",
                    "status": "new",
                    "reply_text": "",
                    "raw": {},
                },
            )
        assert conn.execute(
            "SELECT status FROM comments WHERE comment_id='c1'"
        ).fetchone()["status"] == "replied"
        assert conn.execute(
            "SELECT status FROM comments WHERE comment_id='c2'"
        ).fetchone()["status"] == "ignored"
    finally:
        conn.close()


def test_legacy_reply_text_is_invalidated_for_regeneration(tmp_path):
    db = tmp_path / "rg.db"
    conn = connect(db)
    try:
        _seed(conn)
        conn.execute(
            "UPDATE comments SET reply_text='Старий локальний текст' WHERE comment_id='c1'"
        )
        conn.commit()
    finally:
        conn.close()

    conn = connect(db)
    try:
        row = conn.execute(
            "SELECT draft_state,draft_reason,reply_text FROM comments WHERE comment_id='c1'"
        ).fetchone()
        assert row["draft_state"] == ""
        assert row["draft_reason"] == "legacy_requires_regeneration"
        assert row["reply_text"] == ""
    finally:
        conn.close()


def test_manual_reply_blocks_raw_held_for_review(tmp_path):
    from rg_youtube_control.service import manual_reply

    class FakeClient:
        profile = "main"

        def __init__(self):
            self.sent = []

        def reply(self, comment_id, text):
            self.sent.append((comment_id, text))

    conn = connect(tmp_path / "rg.db")
    try:
        _seed(conn)
        raw = {
            "snippet": {
                "topLevelComment": {
                    "snippet": {"moderationStatus": "heldForReview"}
                }
            }
        }
        conn.execute(
            "UPDATE comments SET raw_json=? WHERE comment_id='c1'",
            (json.dumps(raw),),
        )
        conn.commit()

        client = FakeClient()
        try:
            manual_reply(client, conn, "c1", "Тест")
        except RuntimeError as exc:
            assert "модерації YouTube" in str(exc)
        else:
            raise AssertionError("heldForReview comment was allowed")
        assert client.sent == []
    finally:
        conn.close()


def test_saved_draft_normalizes_long_dash(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _seed(conn)
        assert save_comment_draft(
            conn,
            "c1",
            "Дякуємо — раді вас бачити – завжди.",
            state="ready",
            reason="test",
        )
        row = conn.execute(
            "SELECT reply_text FROM comments WHERE comment_id='c1'"
        ).fetchone()
        assert row["reply_text"] == "Дякуємо - раді вас бачити - завжди."
        assert "—" not in row["reply_text"]
        assert "–" not in row["reply_text"]
    finally:
        conn.close()


def test_safe_template_candidate_uses_fresh_text_classification(tmp_path):
    from rg_youtube_control.service import local_safe_template_candidate

    conn = connect(tmp_path / "rg.db")
    try:
        result = local_safe_template_candidate(
            conn,
            "main",
            "comment-safe-1",
            "Дякую за стрім!",
        )
        assert result is not None
        assert result["state"] == "ready"
        assert result["category"] == "thanks"
        assert result["reply"]
        assert "—" not in result["reply"]
        assert "–" not in result["reply"]

        unsafe = local_safe_template_candidate(
            conn,
            "main",
            "comment-review-1",
            "А що ви думаєте про цю ситуацію?",
        )
        assert unsafe is None
    finally:
        conn.close()


def test_outgoing_manual_reply_normalizes_long_dash(tmp_path):
    from rg_youtube_control.service import manual_reply

    class FakeClient:
        profile = "main"

        def __init__(self):
            self.sent = []

        def reply(self, comment_id, text):
            self.sent.append((comment_id, text))

    conn = connect(tmp_path / "rg.db")
    try:
        _seed(conn)
        client = FakeClient()
        manual_reply(
            client,
            conn,
            "c1",
            "Дякуємо — гарного дня – і до зустрічі.",
        )
        assert client.sent == [
            ("c1", "Дякуємо - гарного дня - і до зустрічі.")
        ]
    finally:
        conn.close()


def test_review_precheck_skips_low_value_reactions():
    from rg_youtube_control.free_tools import _comment_reply_precheck_reason

    assert _comment_reply_precheck_reason("Мдаа!!! 😳😳") == "low_information_reaction"
    assert _comment_reply_precheck_reason("Орк тупий і ржачний") == "insult_or_abuse"
    assert _comment_reply_precheck_reason("Лол 😂😂😂") in {"too_fragmentary", "low_information_reaction"}


def test_review_precheck_skips_aphoristic_text():
    from rg_youtube_control.free_tools import _comment_reply_precheck_reason

    text = "Виростай, мій сину, будь міцний, як криця, виростеш - скажу де правда"
    assert _comment_reply_precheck_reason(text) == "quote_or_aphorism"


def test_review_precheck_allows_clear_question():
    from rg_youtube_control.free_tools import _comment_reply_precheck_reason

    assert _comment_reply_precheck_reason(
        "Почему у них снова такие очереди на заправках?"
    ) == ""


def test_review_precheck_skips_short_statement():
    from rg_youtube_control.free_tools import _comment_reply_precheck_reason

    assert _comment_reply_precheck_reason(
        "Бензина нет, но он есть"
    ) == "short_non_question"


def test_template_rotation_avoids_immediate_repeat(tmp_path):
    from rg_youtube_control.service import _reply_template_for

    conn = connect(tmp_path / "rg.db")
    try:
        _seed(conn)
        first = _reply_template_for(
            conn, "main", "thanks", "rotation-1", "viewer"
        )
        second = _reply_template_for(
            conn, "main", "thanks", "rotation-2", "viewer"
        )
        assert first != second
        assert "—" not in first and "–" not in first
        assert "—" not in second and "–" not in second
    finally:
        conn.close()


def test_comment_background_tasks_do_not_touch_ui_sqlite_connection():
    import inspect
    from rg_youtube_control.ui import MainWindow

    for method in (
        MainWindow.local_comment_reply_selected,
        MainWindow.local_comment_reply_batch,
        MainWindow.local_comment_reply_regenerate_batch,
    ):
        source = inspect.getsource(method)
        task_pos = source.find("def task")
        assert task_pos >= 0
        task_source = source[task_pos:]
        # SQLite/template selection must happen before the worker task starts.
        first_run_tool = task_source.find("self._run_local_tool")
        if first_run_tool >= 0:
            task_source = task_source[:first_run_tool]
        assert "self.conn" not in task_source
        assert "local_safe_template_candidate(" not in task_source
