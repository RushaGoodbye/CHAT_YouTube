from rg_youtube_control.comment_autopilot_guard import unattended_reply_allowed


def check(category="thanks", text="Дякую за ефір!", reply="Дякуємо за підтримку!", **kw):
    return unattended_reply_allowed(category=category, comment_text=text,
                                    reply_text=reply, explicitly_enabled=True, **kw)


def test_opt_in_required():
    assert not unattended_reply_allowed(category="thanks", comment_text="Дякую!",
        reply_text="Дякуємо!", explicitly_enabled=False)[0]


def test_short_thanks_can_pass():
    assert check()[0] is True


def test_questions_and_sensitive_topics_require_review():
    for text in ["Дякую, але коли новий стрім?", "Донат для ЗСУ", "Чи правда про війну?"]:
        assert check(text=text)[0] is False


def test_sensitive_categories_require_review():
    for category in ["donate", "links", "schedule", "question", "toxic"]:
        assert check(category=category)[0] is False


def test_duplicate_and_long_text_are_blocked():
    assert not check(already_replied=True)[0]
    assert not check(text="Дякую " * 100)[0]


def test_service_checks_both_paths():
    from pathlib import Path
    source = Path("src/rg_youtube_control/service.py").read_text(encoding="utf-8")
    assert source.count("_unattended_reply_gate(conn,") >= 2
    assert 'comment_auto_reply_enabled_{profile}' in source
