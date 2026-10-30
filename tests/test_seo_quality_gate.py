from rg_youtube_control import free_tools
from rg_youtube_control.seo_quality_gate import inspect_package, language_error


def sample(**changes):
    value = {
        "title": "Шойгу: що говорять росіяни про кадрові зміни?",
        "title_variants": [
            "Шойгу та кадрові зміни: думки співрозмовників",
            "Чому обговорюють Шойгу в чат-рулетці?",
            "Що думають росіяни про рішення щодо Шойгу?",
        ],
        "description": "У чат-рулетці обговорюють кадрові зміни та роль Шойгу. "
        "Співрозмовники діляться своїми думками про події та сперечаються щодо їхніх причин. "
        "Ведучий ставить уточнювальні запитання, а учасники висловлюють різні погляди. "
        "Відео містить розмову та реакції на обговорювану тему.",
        "tags": ["Шойгу", "чат рулетка", "росіяни", "обговорення", "розмова", "кадрові зміни", "думки", "РАША ГУДБАЙ"],
    }
    value.update(changes)
    return value


def test_clean_ukrainian_package_is_format_ready_but_not_auto_publishable():
    result = inspect_package(sample())
    assert result["format_pass"]
    assert result["editorial_review_required"]
    assert result["problems"] == {}


def test_russian_legacy_title_is_detected_and_localized():
    result = inspect_package(sample(title="Увольнение Шойгу в России"))
    assert result["problems"]["title"] == ["NON_UKRAINIAN"]


def test_exact_field_diagnostics_and_duplicate_detection():
    result = inspect_package(sample(
        title_variants=["Шойгу і зміни"] * 3,
        tags=["Шойгу", "коррупция"],
    ))
    assert "DUPLICATE" in result["problems"]["title_variants"]
    assert "FEWER_THAN_EIGHT" in result["problems"]["tags"]
    assert "NON_UKRAINIAN" in result["problems"]["tags"]


def test_valid_ukrainian_words_are_not_rejected():
    assert not language_error("Росія та корупція: що кажуть росіяни?")
    assert language_error("Россия и коррупция: что говорят россияне?")


def test_generator_and_quality_gate_share_language_decisions():
    for sample_text in (
        "Росія та корупція: що кажуть росіяни?",
        "Шойгу: думки співрозмовників",
        "Россия и коррупция: что говорят россияне?",
        "Увольнение Шойгу в России",
    ):
        assert free_tools._seo_ukrainian_language_issue(sample_text) == language_error(sample_text)
