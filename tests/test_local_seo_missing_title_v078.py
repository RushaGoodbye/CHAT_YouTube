import json
from pathlib import Path

import pytest

from rg_youtube_control import free_tools as ft


GOOD_DESCRIPTION = (
    "У цьому випуску чат-рулетки співрозмовники говорять про ціни на бензин "
    "та проблеми з паливом у Росії. Один учасник стверджує, що черг немає, "
    "а інший описує власний досвід на АЗС. Їхні оцінки причин подорожчання "
    "розходяться. Обговорення охоплює повсякденні витрати та те, як вони "
    "впливають на життя людей. "
)
TRANSCRIPT = ("[00:00] бензин в России, цены на АЗС. " * 60)
CURRENT_TITLE = "ЧАТ РУЛЕТКА. Бензин в России: спор о ценах"


def _mock_related_helpers(monkeypatch):
    monkeypatch.setattr(ft, "_description_quality_error", lambda *_args: "")
    monkeypatch.setattr(ft, "_recover_missing_description", lambda **_kwargs: "")
    monkeypatch.setattr(ft, "_grounded_chapters_from_transcript", lambda **_kwargs: "")


def test_manual_local_seo_falls_back_to_existing_title_without_retries(monkeypatch):
    _mock_related_helpers(monkeypatch)
    calls = []
    def fake_chat(*_args, **_kwargs):
        calls.append("ollama")
        return json.dumps({
            "title": "",
            "description": GOOD_DESCRIPTION,
            "title_variants": [
                "Бензин дорожает: россияне спорят о ценах",
                "Очереди на АЗС: что говорят россияне",
                "Топливо в России: противоречивые ответы",
            ],
            "tags": [],
            "chapters": "",
        }, ensure_ascii=False)

    monkeypatch.setattr(ft, "ollama_chat", fake_chat)
    monkeypatch.setattr(
        ft, "_recover_missing_description",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Do not regenerate already valid descriptions")
        ),
    )
    result = ft.generate_seo_package_local(
        current_title=CURRENT_TITLE,
        transcript=TRANSCRIPT,
        fast_mode=False,
        timeout=1,
    )
    assert result["title"] == CURRENT_TITLE
    assert result["title_fallback_used"] is True
    assert result["needs_review"] is True
    assert result["youtube_data_api_quota"] == 0
    assert len(result["title_variants"]) == 3
    assert len(calls) == 1


def test_manual_local_seo_with_missing_title_and_failed_ab_recovery_is_review_draft(monkeypatch):
    _mock_related_helpers(monkeypatch)
    monkeypatch.setattr(
        ft, "ollama_chat",
        lambda *_args, **_kwargs: json.dumps({
            "title": None,
            "description": GOOD_DESCRIPTION,
            "title_variants": [],
            "tags": [],
            "chapters": "",
        }, ensure_ascii=False),
    )
    monkeypatch.setattr(
        ft, "_recover_title_variants",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("model response invalid")),
    )
    result = ft.generate_seo_package_local(
        current_title=CURRENT_TITLE,
        transcript=TRANSCRIPT,
        fast_mode=False,
        timeout=1,
    )
    assert result["title"] == CURRENT_TITLE
    assert result["title_fallback_used"]
    assert result["title_variants"] == []
    assert result["needs_review"]
    assert result["youtube_data_api_quota"] == 0


def test_model_alt_title_alias_and_string_ab_are_normalized():
    candidate = ft._normalize_seo_candidate({
        "название": "Как россияне спорят о бензине",
        "title_variants": "1. Бензин и цены\n2. Очереди на АЗС\n3. Россияне о топливе",
    })
    assert candidate["title"] == "Как россияне спорят о бензине"
    assert candidate["title_variants"] == [
        "Бензин и цены", "Очереди на АЗС", "Россияне о топливе",
    ]


def test_local_seo_normal_mode_menu_and_missing_ab_stay_in_review():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    section = source[
        source.index('def _normalize_local_seo_package('):
        source.index('def local_seo_batch(')
    ]
    assert "Локальна модель не створила 3 різні A/B" not in section
    save = source[
        source.index("    def _save_local_seo_result("):
        source.index("    def export_public_comments_zero_api(")
    ]
    assert 'bool(package.get("needs_review"))' in save
    assert '"draft" if requires_review else "ready"' in save
    assert 'quality_state="needs_review" if requires_review else "safe"' in save
    assert 'self.advanced_local_seo_action.setVisible(True)' in source


def test_model_without_any_trusted_title_remains_blocked(monkeypatch):
    _mock_related_helpers(monkeypatch)
    monkeypatch.setattr(ft, "ollama_chat", lambda *_args, **_kwargs: '{"title":"","description":"x","title_variants":[]}')
    with pytest.raises(ValueError, match="Немає ані назви"):
        ft.generate_seo_package_local(
            current_title="", transcript=TRANSCRIPT, fast_mode=True, timeout=1
        )



def test_local_seo_without_transcript_requires_manual_review(monkeypatch):
    _mock_related_helpers(monkeypatch)
    monkeypatch.setattr(ft, "ollama_chat", lambda *_args, **_kwargs: json.dumps({
        "title": "Бензин в России: вопросы к властям",
        "description": GOOD_DESCRIPTION,
        "title_variants": [
            "Бензин и цены в России",
            "Очереди на АЗС",
            "Россияне о бензине",
        ],
        "tags": [],
        "chapters": "",
    }, ensure_ascii=False))
    result = ft.generate_seo_package_local(
        current_title=CURRENT_TITLE, transcript="", fast_mode=False, timeout=1
    )
    assert result["needs_review"] is True
    assert "Транскрипт відсутній" in result["review_reason"]
    assert result["youtube_data_api_quota"] == 0
