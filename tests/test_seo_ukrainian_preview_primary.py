import json

from rg_youtube_control import free_tools


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
