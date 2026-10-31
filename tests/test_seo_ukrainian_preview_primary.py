import json

from rg_youtube_control import free_tools
from rg_youtube_control.seo_quality_gate import inspect_package


def test_fast_seo_uses_ukrainian_preview_instead_of_legacy_russian_title(monkeypatch):
    monkeypatch.setattr(
        free_tools, "ollama_chat",
        lambda *a, **k: json.dumps({
            "title": "Увольнение Шойгу в России",
            "title_variants": ["Шойгу: що говорять співрозмовники?",
            "Корупція та Шойгу: думки росіян",
            "Посада Шойгу: чому виникла суперечка?"],
            "description": "У розмові обговорюють Шойгу, призначення та корупційні підозри. "
            "Співрозмовники висловлюють різні думки про причини кадрової зміни. "
            "Ведучий ставить запитання, а учасники діляться припущеннями.",
            "tags": ["Шойгу", "чат рулетка"], "chapters": ""
        }, ensure_ascii=False),
    )
    result = free_tools.generate_seo_package_local(
        current_title="Увольнение Шойгу в России",
        transcript=("[00:05] Шойгу коррупция Путин смена должности. " * 50),
        fast_mode=True,
        timeout=1,
    )
    assert not free_tools._seo_ukrainian_language_issue(result["title"])
    assert result["needs_review"] is True
    assert len(result["title_variants"]) == 3
    assert "назва" not in result["seo_language_issues"]

    expected = inspect_package(result)
    assert result["seo_format_pass"] == expected["format_pass"]
    assert result["seo_format_problems"] == expected["problems"]
    assert result["seo_editorial_review_required"] is True



def test_transcript_only_qa_gets_review_title_without_verified_metadata(monkeypatch):
    monkeypatch.setattr(
        free_tools, "ollama_chat",
        lambda *a, **k: json.dumps({
            "title": "",
            "title_variants": [
                "Шойгу: що говорять співрозмовники?",
                "Корупція та Шойгу: думки росіян",
                "Посада Шойгу: чому виникла суперечка?",
            ],
            "description": "У розмові обговорюють Шойгу, призначення та корупційні підозри. "
            "Співрозмовники висловлюють різні думки про причини кадрової зміни. "
            "Ведучий ставить запитання, а учасники діляться припущеннями.",
            "tags": ["Шойгу", "чат рулетка"],
            "chapters": "",
        }, ensure_ascii=False),
    )
    result = free_tools.generate_seo_package_local(
        current_title="",
        transcript=("[00:05] Шойгу коррупция Путин смена должности. " * 50),
        fast_mode=True,
        timeout=1,
    )
    assert result["title"]
    assert not free_tools._seo_ukrainian_language_issue(result["title"])
    assert result["title_fallback_used"] is True
    assert result["needs_review"] is True
    assert result["seo_editorial_review_required"] is True
