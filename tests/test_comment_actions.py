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


def test_semantic_action_question_stays_review():
    from rg_youtube_control.comment_action_ai import semantic_action_candidate

    result = semantic_action_candidate("Чому вони знову це роблять?")
    assert result["action"] == "review"
    assert result["category"] == "question"


def test_semantic_action_like(monkeypatch):
    from rg_youtube_control import comment_action_ai

    monkeypatch.setattr(
        comment_action_ai,
        "ollama_chat",
        lambda *args, **kwargs: '{"action":"like","reason":"supportive","category":"supportive"}',
    )
    result = comment_action_ai.semantic_action_candidate(
        "Дуже сильний випуск, дивлюся вас давно."
    )
    assert result["action"] == "like"


def test_semantic_action_skip(monkeypatch):
    from rg_youtube_control import comment_action_ai

    monkeypatch.setattr(
        comment_action_ai,
        "ollama_chat",
        lambda *args, **kwargs: '{"action":"skip","reason":"provocation","category":"provocation"}',
    )
    result = comment_action_ai.semantic_action_candidate(
        "Черговий беззмістовний вкид без питання."
    )
    assert result["action"] == "skip"


def test_semantic_action_ollama_error_falls_back_to_review(monkeypatch):
    from rg_youtube_control import comment_action_ai

    def fail(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(comment_action_ai, "ollama_chat", fail)
    result = comment_action_ai.semantic_action_candidate(
        "Неоднозначний змістовний коментар без питання."
    )
    assert result["action"] == "review"
    assert result["reason"].startswith("ollama_error:")


def test_action_ui_is_installed_from_main():
    import inspect
    from rg_youtube_control import main

    source = inspect.getsource(main.main)
    assert "install_comment_action_ui(window)" in source


def test_action_ui_hides_legacy_broad_batches():
    import inspect
    from rg_youtube_control.comment_action_ui import install_comment_action_ui

    source = inspect.getsource(install_comment_action_ui)
    assert 'startswith("Створити x20")' in source
    assert 'startswith("Перегенерувати x20")' in source
    assert "AI REVIEW x20" in source
    assert "Підготувати ВІДПОВІДІ x20" in source


def test_semantic_decision_survives_reopen(tmp_path):
    from rg_youtube_control.db import save_comment_action

    path = tmp_path / "rg.db"
    conn = connect(path)
    try:
        _video(conn)
        upsert_comment(
            conn,
            {
                "comment_id": "persist",
                "video_id": "v1",
                "author": "viewer",
                "text": "Змістовний коментар без питання",
                "published_at": "2026-10-07T10:00:00Z",
                "status": "new",
                "raw": {},
            },
        )
        assert save_comment_action(
            conn,
            "persist",
            action="like",
            reason="semantic:supportive",
            category="supportive",
        )
    finally:
        conn.close()

    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT action,action_reason,category FROM comments WHERE comment_id='persist'"
        ).fetchone()
        assert row["action"] == "like"
        assert row["action_reason"] == "semantic:supportive"
        assert row["category"] == "supportive"
    finally:
        conn.close()


def test_new_duplicate_is_skipped_immediately(tmp_path):
    conn = connect(tmp_path / "rg.db")
    try:
        _video(conn)
        first = {
            "video_id": "v1",
            "author": "viewer",
            "text": "Дякую за вашу працю!",
            "status": "new",
            "raw": {},
        }
        upsert_comment(
            conn,
            {
                **first,
                "comment_id": "first",
                "published_at": "2026-10-07T10:00:00Z",
            },
        )
        upsert_comment(
            conn,
            {
                **first,
                "comment_id": "second",
                "published_at": "2026-10-07T10:05:00Z",
            },
        )
        row = conn.execute(
            "SELECT action,action_reason,category FROM comments WHERE comment_id='second'"
        ).fetchone()
        assert row["action"] == "skip"
        assert row["action_reason"] == "duplicate_same_author_text"
        assert row["category"] == "duplicate"
    finally:
        conn.close()


def test_auto_reply_ui_uses_scanner_setting_and_independent_guard():
    from pathlib import Path
    ui = Path("src/rg_youtube_control/comment_action_ui.py").read_text(encoding="utf-8")
    service = Path("src/rg_youtube_control/service.py").read_text(encoding="utf-8")
    assert 'f"auto_reply_enabled_{window.current_profile}"' in ui
    assert 'f"comment_auto_reply_enabled_{window.current_profile}"' in ui
    assert "_unattended_reply_gate(" in service


def test_unattended_safe_ack_only_after_explicit_enable():
    from rg_youtube_control.comment_autopilot_guard import unattended_reply_allowed
    kwargs = dict(category="thanks", comment_text="Дякую!", reply_text="Дякуємо за підтримку!")
    assert unattended_reply_allowed(**kwargs, explicitly_enabled=False)[0] is False
    assert unattended_reply_allowed(**kwargs, explicitly_enabled=True)[0] is True
    assert unattended_reply_allowed(category="question", comment_text="Що робити?", reply_text="Так", explicitly_enabled=True)[0] is False


def test_auto_reply_preview_is_read_only_and_never_posts(tmp_path):
    from rg_youtube_control.comment_action_runtime import preview_safe_auto_replies
    conn = connect(tmp_path / "preview.db")
    try:
        _video(conn)
        upsert_comment(conn, {
            "comment_id": "preview-1", "video_id": "v1", "author": "viewer",
            "text": "Дякую!", "published_at": "2026-11-02T10:00:00Z",
            "status": "new", "raw": {},
        })
        conn.execute("UPDATE comments SET category='thanks', reply_text='Дякуємо за підтримку!' WHERE comment_id='preview-1'")
        conn.commit()
        before = conn.execute("SELECT status,reply_text FROM comments WHERE comment_id='preview-1'").fetchone()
        stats = preview_safe_auto_replies(conn, "main")
        after = conn.execute("SELECT status,reply_text FROM comments WHERE comment_id='preview-1'").fetchone()
        assert stats["checked"] == 1
        assert stats["eligible"] == 1
        assert tuple(before) == tuple(after)
    finally:
        conn.close()


def test_prepare_action_drafts_never_marks_risky_question_as_ready(tmp_path):
    from rg_youtube_control.comment_action_runtime import prepare_action_reply_drafts
    conn = connect(tmp_path / "drafts.db")
    try:
        _video(conn)
        upsert_comment(conn, {
            "comment_id": "risk1", "video_id": "v1", "author": "viewer",
            "text": "Де збір?", "published_at": "2026-11-02T10:00:00Z",
            "status": "new", "raw": {},
        })
        conn.execute("UPDATE comments SET action='reply', category='donate', draft_state='' WHERE comment_id='risk1'")
        conn.commit()
        stats = prepare_action_reply_drafts(conn, "main")
        row = conn.execute("SELECT draft_state FROM comments WHERE comment_id='risk1'").fetchone()
        assert stats["ready"] == 0
        assert row["draft_state"] != "ready"
    finally:
        conn.close()


def test_diverse_reply_preview_does_not_mutate_database(tmp_path):
    from rg_youtube_control.comment_action_runtime import propose_diverse_safe_replies
    conn = connect(tmp_path / "diverse.db")
    try:
        _video(conn)
        for i in range(12):
            upsert_comment(conn, {
                "comment_id": f"thanks-{i}", "video_id": "v1", "author": f"viewer-{i}",
                "text": "Дякую!", "published_at": "2026-11-02T10:00:00Z",
                "status": "new", "raw": {},
            })
        before = conn.execute("SELECT count(*) FROM comments WHERE draft_state='ready'").fetchone()[0]
        result = propose_diverse_safe_replies(conn, "main")
        after = conn.execute("SELECT count(*) FROM comments WHERE draft_state='ready'").fetchone()[0]
        assert result["proposed"] == 12
        assert result["distinct_replies"] >= 2
        assert result["published"] == 0
        assert before == after
    finally:
        conn.close()


def test_local_personalized_reply_preview_is_review_only(monkeypatch):
    from rg_youtube_control import lm_studio_client, comment_action_runtime
    monkeypatch.setattr(
        lm_studio_client, "lm_studio_chat",
        lambda *_args, **_kwargs: '{"reply":"Дякуємо за вашу увагу до випуску! Цінуємо, що ви дивитесь та підтримуєте нашу роботу."}',
    )
    draft = comment_action_runtime.generate_personal_reply_preview("Дякую за випуск!")
    assert draft["status"] == "DRAFT_REVIEW_REQUIRED"
    assert "Дякуємо" in draft["reply"]


def test_local_personalized_reply_failure_stays_unsent(monkeypatch):
    from rg_youtube_control import lm_studio_client, comment_action_runtime
    def fail(*_args, **_kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(lm_studio_client, "lm_studio_chat", fail)
    draft = comment_action_runtime.generate_personal_reply_preview("Дякую!")
    assert draft == {"status": "LOCAL_MODEL_UNAVAILABLE", "reply": ""}


def test_ai_review_draft_is_persisted_but_never_auto_ready(tmp_path):
    from rg_youtube_control.db import save_comment_draft
    from rg_youtube_control.comment_action_runtime import preview_safe_auto_replies
    conn = connect(tmp_path / "ai-review.sqlite")
    try:
        _video(conn)
        upsert_comment(conn, {
            "comment_id": "historical-comment", "video_id": "v1",
            "author": "viewer", "text": "Фінляндія у 1939 році?",
            "published_at": "2026-11-02T10:00:00Z", "status": "new", "raw": {},
        })
        assert save_comment_draft(
            conn, "historical-comment", "Це питання потребує перевірки джерел.",
            state="review", reason="lm_studio_manual_review_required",
        )
        row = conn.execute(
            "SELECT draft_state,reply_text,status FROM comments WHERE comment_id=?",
            ("historical-comment",),
        ).fetchone()
        assert row["draft_state"] == "review"
        assert row["reply_text"] == "Це питання потребує перевірки джерел."
        assert row["status"] == "new"
        check = preview_safe_auto_replies(conn, "main")
        assert check["eligible"] == 0
    finally:
        conn.close()


def test_ai_historical_claim_requires_fact_check(monkeypatch):
    from rg_youtube_control import lm_studio_client, comment_action_runtime
    monkeypatch.setattr(
        lm_studio_client, "lm_studio_chat",
        lambda *_a, **_k: '{"reply":"У 1939 році відбувалася Зимова війна."}',
    )
    draft = comment_action_runtime.generate_personal_reply_preview("А що було з Фінляндією у 1939 році?")
    assert draft["status"] == "FACT_CHECK_REQUIRED"
    assert "1939" in draft["reply"]


def test_ai_rejects_generic_reply(monkeypatch):
    from rg_youtube_control import lm_studio_client, comment_action_runtime
    monkeypatch.setattr(lm_studio_client, "lm_studio_chat",
                        lambda *_a, **_k: '{"reply":"Дякую за ваш коментар."}')
    result = comment_action_runtime.generate_personal_reply_preview(
        "Фінляндія теж хотіла залишитися незалежною в 1939 році"
    )
    assert result["status"] == "QUALITY_REJECTED"
    assert result["reply"] == ""


def test_local_reply_retries_empty_json_only_once(monkeypatch):
    from rg_youtube_control import lm_studio_client, comment_action_runtime
    responses = iter(['{"reply":""}', '{"reply":"Цінуємо вашу підтримку цього випуску та увагу до конкретних розмов на каналі."}'])
    seen = []
    def generate(*_args, **kwargs):
        seen.append((kwargs["max_tokens"], kwargs["json_mode"]))
        return next(responses)
    monkeypatch.setattr(lm_studio_client, "lm_studio_chat", generate)
    result = comment_action_runtime.generate_personal_reply_preview("Дякую за цей випуск!")
    assert result["status"] == "DRAFT_REVIEW_REQUIRED"
    assert seen == [(512, True), (768, False)]
