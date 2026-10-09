"""Prevent semantic review failures caused by lost real dialogue quotations."""
from __future__ import annotations

from pathlib import Path

from rg_youtube_control.dialogue_seo import preserve_one_grounded_quote


def _report():
    return {
        "blocks": [
            {"verified": True, "topics": [
                {"topic": "Ціни на бензин",
                 "evidence": "Бензин знову подорожчав, і люди це помічають"},
            ]},
            {"verified": True, "topics": [
                {"topic": "Російська пропаганда",
                 "evidence": "По телебаченню кажуть одне, а в житті зовсім інше"},
            ]},
        ],
    }


def test_missing_grounded_quote_is_added_verbatim_without_dropping_topics():
    old = "У діалозі обговорюють Ціни на бензин та Російська пропаганда."
    rewritten, added = preserve_one_grounded_quote(old, _report())
    assert added is True
    assert rewritten.startswith(old)
    assert "Ціни на бензин" in rewritten
    assert "Російська пропаганда" in rewritten
    assert "Бензин знову подорожчав, і люди це помічають" in rewritten
    assert "Дослівний фрагмент розмови:" in rewritten


def test_does_not_double_insert_existing_verified_quote():
    old = "Ціни на бензин. Бензин знову подорожчав, і люди це помічають."
    new, added = preserve_one_grounded_quote(old, _report())
    assert added is False
    assert new == old


def test_idempotent_when_called_again_with_same_report():
    first, inserted = preserve_one_grounded_quote("Ціни на бензин.", _report())
    second, again = preserve_one_grounded_quote(first, _report())
    assert inserted and not again
    assert second == first


def test_unverified_or_missing_quotations_are_never_fabricated():
    report = _report()
    report["blocks"][0]["verified"] = False
    report["blocks"][1]["verified"] = False
    old = "Ціни на бензин."
    text, inserted = preserve_one_grounded_quote(old, report)
    assert not inserted
    assert text == old


def test_byte_limit_keeps_existing_description_without_truncation():
    old = "Дуже важливі підтверджені теми. " * 35
    text, added = preserve_one_grounded_quote(
        old, _report(), max_body_bytes=250,
    )
    assert not added
    assert text == old.strip()
    assert "Бензин знову подорожчав" not in text


def test_generator_uses_quote_preservation_before_review_status():
    code = (
        Path(__file__).resolve().parents[1]
        / "src/rg_youtube_control/free_tools.py"
    ).read_text(encoding="utf-8")
    main = code.split("def generate_seo_package_local(", 1)[1].split(
        "def _comment_reply_safe_novelty_ok(", 1
    )[0]
    assert "description, grounded_quote_added = preserve_one_grounded_quote(" in main
    assert main.index("description, omitted_topics = preserve_outline_topics(") < main.index(
        "description, grounded_quote_added = preserve_one_grounded_quote("
    )
    assert '"timeline_grounded_quote_added": grounded_quote_added' in main
